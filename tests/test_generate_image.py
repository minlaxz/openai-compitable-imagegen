"""Offline tests: no credentials, network calls, or paid image requests."""

import base64
import contextlib
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_image as imagegen


ENV = {
    "OPENAI_IMAGE_BASE_URL": "https://images.example.invalid/v1",
    "OPENAI_IMAGE_MODEL": "gpt-6-astra",
    "OPENAI_IMAGE_API_KEY": "test-only-image-secret",
}


def image_bytes(image_format="PNG", size=(8, 8)):
    stream = BytesIO()
    Image.new("RGB", size, color="green").save(stream, format=image_format)
    return stream.getvalue()


def response_for(data=None, **call_changes):
    call = {
        "type": "image_generation_call",
        "status": "completed",
        "result": base64.b64encode(image_bytes() if data is None else data).decode("ascii"),
    }
    call.update(call_changes)
    return SimpleNamespace(status="completed", output=[SimpleNamespace(**call)])


class ConfigurationTests(unittest.TestCase):
    def test_dedicated_configuration_only(self):
        env = dict(ENV, OPENAI_API_KEY="unrelated", OPENAI_BASE_URL="https://unrelated.invalid")
        with patch.dict(os.environ, env, clear=True):
            config = imagegen.read_config()
        self.assertEqual(config.api_key, ENV["OPENAI_IMAGE_API_KEY"])
        self.assertEqual(config.base_url, ENV["OPENAI_IMAGE_BASE_URL"])
        self.assertEqual(config.model, "gpt-6-astra")
        self.assertNotIn(config.api_key, repr(config))

    def test_no_generic_fallback_or_defaults(self):
        env = {"OPENAI_API_KEY": "unrelated", "OPENAI_API_BASE": "https://unrelated.invalid"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(imagegen.GenerationError) as caught:
                imagegen.read_config()
        for name in imagegen.REQUIRED_ENV:
            self.assertIn(name, str(caught.exception))
        self.assertNotIn("unrelated", str(caught.exception))

    def test_each_variable_is_required(self):
        for name in ENV:
            with self.subTest(name=name), patch.dict(os.environ, dict(ENV, **{name: "  "}), clear=True):
                with self.assertRaisesRegex(imagegen.GenerationError, name):
                    imagegen.read_config()

    def test_unsafe_urls_rejected_without_echo(self):
        urls = [
            "http://images.example.invalid/v1",
            "https://user:SECRET@images.example.invalid/v1",
            "https://images.example.invalid/v1?key=SECRET",
            "https://images.example.invalid/v1#SECRET",
            "https://images.example.invalid:bad/v1",
            "https://images.example.invalid:0/v1",
            "https://",
            "https://[invalid",
            "https://images.example.invalid/SECRET path",
        ]
        for url in urls:
            with self.subTest(url=url), patch.dict(os.environ, dict(ENV, OPENAI_IMAGE_BASE_URL=url), clear=True):
                with self.assertRaises(imagegen.GenerationError) as caught:
                    imagegen.read_config()
                self.assertNotIn("SECRET", str(caught.exception))

    def test_client_has_explicit_destination_timeout_and_no_retries(self):
        with patch.dict(os.environ, ENV, clear=True), patch("openai.OpenAI") as constructor:
            config = imagegen.read_config()
            imagegen.build_client(config, 45)
        constructor.assert_called_once_with(
            api_key=ENV["OPENAI_IMAGE_API_KEY"], base_url=ENV["OPENAI_IMAGE_BASE_URL"],
            timeout=45, max_retries=0,
        )


class RequestTests(unittest.TestCase):
    def test_real_sdk_serialization_with_mock_transport(self):
        data = image_bytes()

        def handle(request):
            self.assertEqual(str(request.url), ENV["OPENAI_IMAGE_BASE_URL"] + "/responses")
            self.assertEqual(request.headers["authorization"], "Bearer " + ENV["OPENAI_IMAGE_API_KEY"])
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-6-astra")
            self.assertEqual(payload["tool_choice"], "required")
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "model": "gpt-6-astra", "status": "completed",
                "output": [{"id": "img_test", "type": "image_generation_call", "status": "completed",
                            "result": base64.b64encode(data).decode("ascii")}],
            })

        with patch.dict(os.environ, ENV, clear=True):
            config = imagegen.read_config()
        with OpenAI(
            api_key=config.api_key, base_url=config.base_url, max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        ) as client:
            response = imagegen.create_request(client, config, imagegen.parse_args(["test"]), "png")
        self.assertEqual(imagegen.extract_image(response, "png", None), data)

    def test_request_controls_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            reference.write_bytes(image_bytes())
            args = imagegen.parse_args([
                "--image", str(reference), "--size", "1024x1024", "--quality", "high",
                "--background", "transparent", "Keep the face unchanged",
            ])
            client = MagicMock()
            with patch.dict(os.environ, ENV, clear=True):
                imagegen.create_request(client, imagegen.read_config(), args, "png")
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-6-astra")
        self.assertEqual(request["tool_choice"], "required")
        self.assertEqual(request["tools"], [{
            "type": "image_generation", "output_format": "png", "size": "1024x1024",
            "quality": "high", "background": "transparent",
        }])
        content = request["input"][0]["content"]
        self.assertEqual(content[0]["text"], "Keep the face unchanged")
        self.assertTrue(content[1]["image_url"].startswith("data:image/png;base64,"))

    def test_optional_controls_are_not_sent_by_default(self):
        client = MagicMock()
        with patch.dict(os.environ, ENV, clear=True):
            imagegen.create_request(client, imagegen.read_config(), imagegen.parse_args(["test"]), "webp")
        self.assertEqual(client.responses.create.call_args.kwargs["tools"], [
            {"type": "image_generation", "output_format": "webp"},
        ])

    def test_invalid_reference_does_not_make_request(self):
        client = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.png"
            path.write_bytes(b"not an image")
            args = imagegen.parse_args(["--image", str(path), "test"])
            with patch.dict(os.environ, ENV, clear=True), self.assertRaises(imagegen.GenerationError):
                imagegen.create_request(client, imagegen.read_config(), args, "png")
        client.responses.create.assert_not_called()

    def test_oversized_reference_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.png"
            path.write_bytes(image_bytes())
            with patch.object(imagegen, "MAX_REFERENCE_BYTES", 4), self.assertRaises(imagegen.GenerationError):
                imagegen.reference_content(path)


class ArtifactTests(unittest.TestCase):
    def test_valid_formats(self):
        for image_format in ("png", "jpeg", "webp"):
            with self.subTest(image_format=image_format):
                data = image_bytes(image_format.upper())
                self.assertEqual(imagegen.extract_image(response_for(data), image_format, None), data)

    def test_invalid_base64(self):
        for result in ("!!!!", "aGVsbG8=\n", "", None, "\u2603"):
            with self.subTest(result=result), self.assertRaises(imagegen.GenerationError):
                imagegen.extract_image(response_for(result=result), "png", None)

    def test_non_image_bytes(self):
        with self.assertRaises(imagegen.GenerationError):
            imagegen.extract_image(response_for(b"hello"), "png", None)

    def test_wrong_format_and_size(self):
        for image_format, size in (("jpeg", None), ("png", "1024x1024")):
            with self.subTest(image_format=image_format, size=size), self.assertRaises(imagegen.GenerationError):
                imagegen.extract_image(response_for(), image_format, size)

    def test_requested_size_accepted(self):
        data = image_bytes(size=(1024, 1024))
        self.assertEqual(imagegen.extract_image(response_for(data), "png", "1024x1024"), data)

    def test_missing_failed_pending_and_multiple_calls(self):
        good = response_for()
        responses = [
            SimpleNamespace(status="completed", output=[]),
            SimpleNamespace(status="failed", output=good.output),
            SimpleNamespace(status="queued", output=[]),
            SimpleNamespace(status="in_progress", output=[]),
            SimpleNamespace(status="completed", output=good.output * 2),
            response_for(status="in_progress"),
            response_for(status="failed"),
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(imagegen.GenerationError):
                imagegen.extract_image(response, "png", None)

    def test_save_preserves_existing_file_unless_authorized(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "image.png"
            output.write_bytes(b"original")
            with self.assertRaises(imagegen.GenerationError):
                imagegen.save_image(output, b"replacement", False)
            self.assertEqual(output.read_bytes(), b"original")
            imagegen.save_image(output, b"replacement", True)
            self.assertEqual(output.read_bytes(), b"replacement")
            self.assertEqual(list(Path(directory).iterdir()), [output])


class CommandTests(unittest.TestCase):
    def run_main(self, args):
        stdout, stderr = StringIO(), StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = imagegen.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_offline_configuration_check(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(imagegen, "build_client") as client:
            code, stdout, stderr = self.run_main(["--check-config"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertNotIn(ENV["OPENAI_IMAGE_API_KEY"], stdout)
        self.assertNotIn(ENV["OPENAI_IMAGE_BASE_URL"], stdout)
        client.assert_not_called()

    def test_missing_configuration_stops_before_client(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(imagegen, "build_client") as client:
            code, _, stderr = self.run_main(["test"])
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_IMAGE_API_KEY", stderr)
        client.assert_not_called()

    def test_successful_end_to_end_with_mock_api(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True):
            output = Path(directory) / "nested" / "image.png"
            client = MagicMock()
            client.__enter__.return_value.responses.create.return_value = response_for()
            with patch.object(imagegen, "build_client", return_value=client):
                code, stdout, stderr = self.run_main(["--output", str(output), "test"])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(output.read_bytes(), image_bytes())
            self.assertIn("gpt-6-astra", stdout)
            self.assertNotIn(ENV["OPENAI_IMAGE_API_KEY"], stdout + stderr)

    def test_bad_payload_leaves_existing_output_untouched(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True):
            output = Path(directory) / "image.png"
            output.write_bytes(b"original")
            client = MagicMock()
            client.__enter__.return_value.responses.create.return_value = response_for(b"hello")
            with patch.object(imagegen, "build_client", return_value=client):
                code, _, _ = self.run_main(["--overwrite", "--output", str(output), "test"])
            self.assertEqual(code, 1)
            self.assertEqual(output.read_bytes(), b"original")

    def test_invalid_output_stops_before_client(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True):
            existing = Path(directory) / "existing.png"
            existing.touch()
            cases = [
                ["--output", str(existing), "test"],
                ["--output", str(Path(directory) / "x.gif"), "test"],
                ["--output", str(Path(directory) / "x.jpg"), "--background", "transparent", "test"],
            ]
            for args in cases:
                with self.subTest(args=args), patch.object(imagegen, "build_client") as client:
                    code, _, _ = self.run_main(args)
                    self.assertEqual(code, 1)
                    client.assert_not_called()

    def test_secret_not_echoed_from_upstream_exception(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(
            imagegen, "build_client", side_effect=RuntimeError(ENV["OPENAI_IMAGE_API_KEY"])
        ):
            code, stdout, stderr = self.run_main(["test"])
        self.assertEqual(code, 1)
        self.assertNotIn(ENV["OPENAI_IMAGE_API_KEY"], stdout + stderr)

    def test_safe_api_errors(self):
        request = httpx.Request("POST", "https://images.example.invalid/v1/responses")
        secret = ENV["OPENAI_IMAGE_API_KEY"]
        for status in (400, 401, 403, 404, 429, 500):
            error = APIStatusError(secret, response=httpx.Response(status, request=request), body={"key": secret})
            with self.subTest(status=status):
                self.assertNotIn(secret, imagegen.safe_error(error))
        self.assertIn("timed out", imagegen.safe_error(APITimeoutError(request=request)))
        self.assertIn("Could not reach", imagegen.safe_error(APIConnectionError(message=secret, request=request)))

    def test_bad_timeout_and_empty_prompt(self):
        for args in (["--timeout", "0", "test"], ["--timeout", "nan", "test"], ["--timeout", "inf", "test"], ["  "]):
            with self.subTest(args=args), contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                imagegen.parse_args(args)


if __name__ == "__main__":
    unittest.main()
