#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openai>=2.0,<3.0", "Pillow>=12.0,<13.0"]
# ///
"""Generate or edit an image through an explicitly configured Responses API.

Run with ``uv run generate_image.py ...`` (dependencies resolve from the inline
metadata above) or with any interpreter that has requirements.txt installed.

Required environment variables (from a connector or the launching environment):
  OPENAI_IMAGE_BASE_URL
  OPENAI_IMAGE_MODEL
  OPENAI_IMAGE_API_KEY

No .env files, generic OpenAI variables, or default endpoints are used.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass, field
from io import BytesIO
import logging
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit
import warnings

REQUIRED_ENV = (
    "OPENAI_IMAGE_BASE_URL",
    "OPENAI_IMAGE_MODEL",
    "OPENAI_IMAGE_API_KEY",
)
FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
TOOL_OPTIONS = ("size", "background", "quality", "input_fidelity")


class GenerationError(Exception):
    """A locally authored error safe to show without upstream response data."""


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = field(repr=False)


def warn(message: str) -> None:
    print("IMAGE_GENERATION_WARNING: " + message, file=sys.stderr)


def read_config() -> Config:
    values = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV}
    missing = [name for name in REQUIRED_ENV if not values[name]]
    if missing:
        raise GenerationError("Missing required environment variables: " + ", ".join(missing))
    try:
        url = urlsplit(values["OPENAI_IMAGE_BASE_URL"])
        valid = (
            url.scheme == "https"
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.port != 0
            and not any(char.isspace() or ord(char) < 32 for char in values["OPENAI_IMAGE_BASE_URL"])
        )
    except ValueError:
        valid = False
    if not valid:
        raise GenerationError(
            "OPENAI_IMAGE_BASE_URL must be an HTTPS API base URL without credentials, "
            "query parameters, or fragments (usually ending in /v1)."
        )
    return Config(
        base_url=values["OPENAI_IMAGE_BASE_URL"].rstrip("/"),
        model=values["OPENAI_IMAGE_MODEL"],
        api_key=values["OPENAI_IMAGE_API_KEY"],
    )


def build_client(config: Config, timeout: float) -> Any:
    from openai import OpenAI

    # SDK debug logging can expose prompts and reference images.
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # The SDK constructor reads these from the environment and sends them as
    # headers; they belong to unrelated OpenAI accounts, not this endpoint.
    for name in ("OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_WEBHOOK_SECRET", "OPENAI_CUSTOM_HEADERS"):
        os.environ.pop(name, None)
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=timeout,
        max_retries=0,
    )


def inspect_image(data: bytes) -> tuple[str, tuple[int, int]]:
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = (image.format or "").lower()
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                size = image.size
    except Exception:
        raise GenerationError("Image data is corrupt, unsupported, or exceeds safe dimensions.") from None
    if image_format not in {"png", "jpeg", "webp"}:
        raise GenerationError("Only PNG, JPEG, and WebP images are supported.")
    return image_format, size


def reference_content(path: Path) -> dict[str, str]:
    try:
        with path.expanduser().open("rb") as source:
            data = source.read(MAX_REFERENCE_BYTES + 1)
    except OSError:
        raise GenerationError("Cannot read a reference image. Check its path and permissions.") from None
    if len(data) > MAX_REFERENCE_BYTES:
        raise GenerationError("Each reference image must be at most 20 MiB.")
    image_format, _ = inspect_image(data)
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "input_image", "image_url": f"data:image/{image_format};base64,{encoded}"}


def create_request(client: Any, config: Config, args: argparse.Namespace, image_format: str) -> Any:
    content = [{"type": "input_text", "text": args.prompt}]
    content.extend(reference_content(path) for path in args.image)
    tool = {"type": "image_generation", "output_format": image_format}
    for name in TOOL_OPTIONS:
        value = getattr(args, name)
        if value is not None:
            tool[name] = value
    return client.responses.create(
        model=config.model,
        tools=[tool],
        tool_choice="required",
        input=[{"role": "user", "content": content}],
    )


def model_text(response: Any) -> str:
    """Assistant text in the response (for example a refusal), trimmed for an error message."""
    parts = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for chunk in getattr(item, "content", None) or []:
            text = getattr(chunk, "text", None) or getattr(chunk, "refusal", None)
            if isinstance(text, str) and text.strip():
                parts.append(" ".join(text.split()))
    return " ".join(parts)[:300]


def select_call(response: Any) -> Any:
    """Return the completed image_generation_call to save, or raise a safe error."""
    status = getattr(response, "status", None)
    if status in {"queued", "in_progress"}:
        raise GenerationError(
            "The response is still pending. This helper supports synchronous output only; "
            "follow the provider's documented polling workflow rather than submitting again."
        )
    if status not in {None, "completed"}:
        raise GenerationError("The response did not complete. No image was saved.")
    calls = [
        item for item in (getattr(response, "output", None) or [])
        if getattr(item, "type", None) == "image_generation_call"
    ]
    if not calls:
        text = model_text(response)
        raise GenerationError(
            "The response contained no image_generation_call. No image was saved."
            + (f" Model text: {text}" if text else "")
        )
    completed = [
        call for call in calls
        if getattr(call, "status", None) in {None, "completed"}
        and isinstance(getattr(call, "result", None), str)
        and call.result
    ]
    if not completed:
        raise GenerationError("No image-generation call completed with Base64 image data. No image was saved.")
    if len(calls) > 1:
        warn(f"The model made {len(calls)} image calls; only the first completed one is used.")
    return completed[0]


def decode_image(call: Any, expected_format: str, expected_size: str | None) -> bytes:
    """Decode and validate the call's image. Mismatches warn instead of discarding paid output."""
    try:
        data = base64.b64decode(call.result, validate=True)
    except (binascii.Error, ValueError):
        raise GenerationError("The image result was not valid Base64 data.") from None
    image_format, size = inspect_image(data)
    if image_format != expected_format:
        warn(
            f"The provider returned {image_format.upper()} data but the output extension requests "
            f"{expected_format.upper()}; saved unchanged."
        )
    if expected_size and expected_size != "auto":
        if size != tuple(int(part) for part in expected_size.split("x")):
            warn(f"The provider returned {size[0]}x{size[1]} instead of the requested {expected_size}; saved anyway.")
    return data


def save_image(output: Path, data: bytes, overwrite: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".imagegen-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if overwrite:
            os.replace(temporary, output)
        else:
            # Publish the complete file without overwriting a concurrently created output.
            os.link(temporary, output)
    except FileExistsError:
        raise GenerationError("Output already exists. Choose a new path or use --overwrite.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_error(exc: Exception) -> str:
    if isinstance(exc, GenerationError):
        return str(exc)
    if isinstance(exc, ImportError):
        return "Missing a dependency. Run with `uv run`, or install requirements.txt in the selected Python environment."
    if isinstance(exc, OSError):
        return "A local file operation failed. Check paths, permissions, and available disk space."
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except ImportError:
        return "Image generation failed. No upstream error details were printed."
    if isinstance(exc, APITimeoutError):
        return "The API request timed out. It may still be processing; do not automatically resubmit."
    if isinstance(exc, APIConnectionError):
        return "Could not reach the configured endpoint. Check network access; do not automatically resubmit."
    if isinstance(exc, APIStatusError):
        messages = {
            400: "The endpoint rejected the request. Check supported model and image-tool options.",
            401: "Authentication failed. Check OPENAI_IMAGE_API_KEY through your secure configuration.",
            403: "Permission denied. Check the configured credential's model and image-tool access.",
            404: "Endpoint or model not found. Check OPENAI_IMAGE_BASE_URL and OPENAI_IMAGE_MODEL.",
            429: "The endpoint rate limit or quota was exceeded. No automatic retry was made.",
        }
        message = messages.get(exc.status_code, "The endpoint returned an API error. No automatic retry was made.")
        return f"{message} (HTTP {exc.status_code}{error_code(exc)})"
    return "Image generation failed. No upstream error details were printed."


def error_code(exc: Any) -> str:
    """Short structured error code/type from the upstream body, never its free-text message."""
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return ""
    parts = []
    for key in ("type", "code"):
        value = error.get(key)
        if isinstance(value, str) and 0 < len(value) <= 64 and value.replace("_", "").replace("-", "").replace(".", "").isalnum():
            parts.append(value)
    return ", " + "/".join(parts) if parts else ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="Image prompt; use -- before a prompt starting with '-'")
    parser.add_argument("-o", "--output", type=Path, default=Path("generated_image.png"))
    parser.add_argument("--image", type=Path, action="append", default=[], help="Local reference image; repeatable")
    parser.add_argument("--size", choices=("auto", "1024x1024", "1536x1024", "1024x1536"))
    parser.add_argument("--background", choices=("auto", "opaque", "transparent"))
    parser.add_argument("--quality", choices=("auto", "low", "medium", "high"))
    parser.add_argument("--input-fidelity", choices=("high", "low"), help="Reference-image fidelity for edits; requires --image")
    parser.add_argument("--timeout", type=float, default=300, help="SDK request timeout in seconds (default: 300)")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacement of an existing output")
    parser.add_argument("--check-config", action="store_true", help="Validate environment only, without a network call")
    args = parser.parse_args(argv)
    if not args.check_config and (not args.prompt or not args.prompt.strip()):
        parser.error("a nonempty prompt is required unless --check-config is used")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number")
    if not args.check_config and args.input_fidelity and not args.image:
        parser.error("--input-fidelity requires at least one --image")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = read_config()
        if args.check_config:
            print("Configuration is present and structurally valid. Credentials and provider capabilities were not tested.")
            return 0
        image_format = FORMATS.get(args.output.suffix.lower())
        if image_format is None:
            raise GenerationError("Output must use a .png, .jpg, .jpeg, or .webp extension.")
        if args.background == "transparent" and image_format == "jpeg":
            raise GenerationError("Transparent backgrounds require PNG or WebP output.")
        output = args.output.expanduser().absolute()
        if output.is_dir():
            raise GenerationError("Output is a directory. Choose an image file path.")
        if os.path.lexists(output) and not args.overwrite:
            raise GenerationError("Output already exists. Choose a new path or use --overwrite.")
        # Check decoder availability before making a potentially billable request.
        from PIL import Image  # noqa: F401

        with build_client(config, args.timeout) as client:
            response = create_request(client, config, args, image_format)
        call = select_call(response)
        data = decode_image(call, image_format, args.size)
        save_image(output, data, args.overwrite)
    except Exception as exc:
        print("IMAGE_GENERATION_ERROR: " + safe_error(exc), file=sys.stderr)
        return 1
    print(f"Generated {output} using model {config.model}")
    revised = getattr(call, "revised_prompt", None)
    if isinstance(revised, str) and revised.strip() and revised.strip() != args.prompt.strip():
        print("Revised prompt: " + revised.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
