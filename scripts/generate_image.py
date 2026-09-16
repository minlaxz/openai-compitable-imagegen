#!/usr/bin/env python3
"""Generate or edit an image through an explicitly configured Responses API.

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


class GenerationError(Exception):
    """A locally authored error safe to show without upstream response data."""


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = field(repr=False)


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
    for name in ("size", "background", "quality"):
        value = getattr(args, name)
        if value is not None:
            tool[name] = value
    return client.responses.create(
        model=config.model,
        tools=[tool],
        tool_choice="required",
        input=[{"role": "user", "content": content}],
    )


def extract_image(response: Any, expected_format: str, expected_size: str | None) -> bytes:
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
        raise GenerationError("The response contained no image_generation_call. No image was saved.")
    if len(calls) != 1:
        raise GenerationError("Expected one image result; received multiple calls. No image was saved.")
    call = calls[0]
    if getattr(call, "status", None) not in {None, "completed"}:
        raise GenerationError("The image-generation call did not complete. No image was saved.")
    result = getattr(call, "result", None)
    if not isinstance(result, str) or not result:
        raise GenerationError("The image-generation call returned no Base64 image data.")
    try:
        data = base64.b64decode(result, validate=True)
    except (binascii.Error, ValueError):
        raise GenerationError("The image result was not valid Base64 data.") from None
    image_format, size = inspect_image(data)
    if image_format != expected_format:
        raise GenerationError("The returned image format does not match the requested output extension.")
    if expected_size and expected_size != "auto":
        dimensions = tuple(int(part) for part in expected_size.split("x"))
        if size != dimensions:
            raise GenerationError("The returned image dimensions do not match the requested size.")
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
        return "Missing a dependency. Install the skill's requirements.txt in the selected Python environment."
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
        return messages.get(exc.status_code, "The endpoint returned an API error. No automatic retry was made.")
    return "Image generation failed. No upstream error details were printed."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="Image prompt; use -- before a prompt starting with '-'")
    parser.add_argument("-o", "--output", type=Path, default=Path("generated_image.png"))
    parser.add_argument("--image", type=Path, action="append", default=[], help="Local reference image; repeatable")
    parser.add_argument("--size", choices=("auto", "1024x1024", "1536x1024", "1024x1536"))
    parser.add_argument("--background", choices=("auto", "opaque", "transparent"))
    parser.add_argument("--quality", choices=("auto", "low", "medium", "high"))
    parser.add_argument("--timeout", type=float, default=300, help="SDK request timeout in seconds (default: 300)")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacement of an existing output")
    parser.add_argument("--check-config", action="store_true", help="Validate environment only, without a network call")
    args = parser.parse_args(argv)
    if not args.check_config and (not args.prompt or not args.prompt.strip()):
        parser.error("a nonempty prompt is required unless --check-config is used")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number")
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
        if os.path.lexists(output) and not args.overwrite:
            raise GenerationError("Output already exists. Choose a new path or use --overwrite.")
        if output.is_dir():
            raise GenerationError("Output is a directory. Choose an image file path.")
        # Check decoder availability before making a potentially billable request.
        from PIL import Image  # noqa: F401

        with build_client(config, args.timeout) as client:
            response = create_request(client, config, args, image_format)
        data = extract_image(response, image_format, args.size)
        save_image(output, data, args.overwrite)
    except Exception as exc:
        print("IMAGE_GENERATION_ERROR: " + safe_error(exc), file=sys.stderr)
        return 1
    print(f"Generated {output} using model {config.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
