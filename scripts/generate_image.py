#!/usr/bin/env python3
"""Generate an image through an OpenAI-compatible Responses API endpoint.

Required environment variables:
  OPENAI_API_KEY

Optional environment variables:
  OPENAI_IMAGE_BASE_URL, OPENAI_BASE_URL, or OPENAI_API_BASE
  OPENAI_IMAGE_MODEL (default: gpt-6-astra)

The endpoint is expected to support the Responses API and the image_generation
built-in tool. When the Configured OpenAI Connector is enabled, its injected
OPENAI_API_KEY and OPENAI_API_BASE variables are used automatically. The script
never prints the API key.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

DEFAULT_BASE_URL = "https://router.next-innovations.ltd/v1"
DEFAULT_MODEL = "gpt-6-astra"


def build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    base_url = (
        os.getenv("OPENAI_IMAGE_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or DEFAULT_BASE_URL
    )
    return OpenAI(api_key=api_key, base_url=base_url)


def create_request(client: OpenAI, model: str, prompt: str) -> Any:
    return client.responses.create(
        model=model,
        tools=[{"type": "image_generation"}],
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    )


def find_image_call(response: Any) -> Any:
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "image_generation_call":
            return item
    raise RuntimeError("The response contained no image_generation_call")


def extract_result(image_call: Any) -> bytes:
    result = getattr(image_call, "result", None)
    if not result:
        status = getattr(image_call, "status", "unknown")
        raise RuntimeError(
            f"The image call returned no image data (status={status}). "
            "The endpoint may require polling or may not support image output."
        )
    try:
        return base64.b64decode(result)
    except Exception as exc:
        raise RuntimeError("The image result was not valid Base64 data") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Image-generation prompt")
    parser.add_argument(
        "-o",
        "--output",
        default="generated_image.png",
        help="Output PNG path (default: generated_image.png)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_IMAGE_MODEL", DEFAULT_MODEL),
        help="Model name (default: OPENAI_IMAGE_MODEL or gpt-6-astra)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        client = build_client()
        response = create_request(client, args.model, args.prompt)
        image_call = find_image_call(response)
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(extract_result(image_call))
    except Exception as exc:
        print(f"IMAGE_GENERATION_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Generated {output_path} using model {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
