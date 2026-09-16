---
name: openai-compatible-imagegen
description: "Use instead of the host's built-in image tool whenever OPENAI_IMAGE_BASE_URL, OPENAI_IMAGE_MODEL, and OPENAI_IMAGE_API_KEY are set. Generates new images and makes semantic edits to reference images through the user's OpenAI-compatible Responses API."
---

# OpenAI-Compatible Image Generation

The user's configured endpoint is the preferred image route. Every generation goes through the bundled helper, `scripts/generate_image.py`, which calls `/responses` with `OPENAI_IMAGE_MODEL` verbatim and the `image_generation` tool required. The one exception is a host whose connector exposes an image tool instead of environment variables; [`HOSTS.md`](HOSTS.md) covers that. Resolve `SKILL_DIR` to the directory containing this file from its loaded path; the examples below assume it is set.

## Workflow

1. **Classify.** Visual assets and semantic edits go through this skill. Exact charts, numeric plots, and formal diagrams go through deterministic rendering instead.
2. **Preflight.** Run `--check-config` (see Setup). Done when it passes. On failure it names the problem variable: stop, and ask once for secure configuration of that name (see Secrets); host-specific fixes are in [`HOSTS.md`](HOSTS.md).
3. **Prepare the prompt.** Carry the user's intent and required wording verbatim. Add framing, lighting, palette, material, and exclusions only where they help. For edits, state explicitly what must stay unchanged. Done when every user-stated constraint appears in the prompt.
4. **Run the helper** with a writable output path and any user-requested controls (see Controls).
5. **Validate.** Exit 0 prints `Generated <path> using model <model>` on stdout. Read stderr: any `IMAGE_GENERATION_WARNING:` line (size or format mismatch, more than one image call) is disclosed to the user. A `Revised prompt:` line on stdout means the orchestrating model changed the prompt; compare it against required wording. Open the image with the host's viewer and check wording, composition, and edit constraints; if no viewer is available, say so. One regeneration at most unless the user asks for more.
6. **Deliver.** Attach the file through the host's artifact mechanism, or give the path. Name the configured model and say the compatible endpoint was used. The deliverable is the file only, never response JSON, Base64, or credentials.

### New image

```bash
python3 "$SKILL_DIR/scripts/generate_image.py" \
  --output ./artifacts/poster.png \
  --size 1024x1536 \
  -- "A portrait-format travel poster with the exact title: NIGHT TRAIN"
```

### Reference image or semantic edit

```bash
python3 "$SKILL_DIR/scripts/generate_image.py" \
  --image ./reference.png \
  --output ./artifacts/edited.png \
  -- "Change only the jacket to dark green. Preserve the person's face, pose, and background."
```

Add `--input-fidelity high` when faces, logos, or fine details must survive. Send only references authorized for that provider. Generative edits are semantic, not pixel-exact; mask editing is not implemented.

### Controls

`--help` lists the flags and their choices. What it leaves out:

- Output extension (`.png`, `.jpg`, `.jpeg`, `.webp`) selects the format; default path is `generated_image.png`. Existing files are protected unless `--overwrite` is passed.
- `--background transparent` requires PNG or WebP.
- `--image` accepts PNG, JPEG, or WebP up to 20 MiB each, repeatable, sent as `input_image` data URLs.
- Size, background, quality, and input fidelity are sent only when supplied; support is provider-dependent. If the endpoint rejects a user-required control, report it rather than dropping it.
- Sizes other than the listed three: describe the framing in the prompt and disclose the approximation.
- `--timeout` is the SDK request timeout, not a wall-clock bound. SDK retries are disabled, so one invocation is at most one paid request.

## Failures

Every helper failure prints one `IMAGE_GENERATION_ERROR:` line on stderr and exits 1. API errors carry the HTTP status and, when the provider sends one, its structured error code, never the upstream message body. Invalid arguments exit 2 with argparse usage text instead.

- **Authentication or permissions:** report the safe error category and stop. One attempt.
- **Model, endpoint, or tool unsupported:** check configured settings and provider documentation through approved tools. Change the model only with user authorization.
- **Rate limit, timeout, connection failure, or server error:** the request may have been accepted and charged. Explain that before any second attempt.
- **Pending response:** the helper does not poll. Use the provider's documented retrieval workflow if authorized; otherwise report and stop.
- **Text-only, empty, or malformed image output:** no artifact was saved. A response with no image call at all carries a `Model text:` excerpt (up to 300 characters, often a refusal); relay it. One text-only response says nothing about the provider's capability in general.
- **Alternative route:** switch to another provider or the built-in image tool only when it exists and the user has approved the fallback. Preserve the prompt, disclose the switch, and weigh reference-image privacy and cost. Otherwise stop with a one-line explanation.

## Setup

Python 3.10+, `openai`, `Pillow`. The script declares them inline (PEP 723); `requirements.txt` carries the same pins.

With `uv`:

```bash
uv run "$SKILL_DIR/scripts/generate_image.py" --check-config
```

Without `uv`, use an environment that has the dependencies or create one in a writable location under the host's install and network rules:

```bash
python3 -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/python" -m pip install -r "$SKILL_DIR/requirements.txt"
"$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/generate_image.py" --check-config
```

Use the same launcher for every call; the examples above write `python3` for brevity. `--check-config` is offline and runs before `openai` or `Pillow` are imported, so it works before dependencies are installed. It checks the three variables are present and the URL is a clean HTTPS base (no credentials, query, or fragment). No authentication, no network.

## Configuration

The helper reads exactly `OPENAI_IMAGE_BASE_URL`, `OPENAI_IMAGE_MODEL`, and `OPENAI_IMAGE_API_KEY` from its parent process. The base URL is the API root, normally ending in `/v1`; the helper appends `/responses` itself, so a URL that already ends in `/responses` gets a 404. It ignores `.env` files and the generic `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_BASE`, `OPENAI_ORG_ID`, and `OPENAI_PROJECT_ID`, so credentials from unrelated services never mix. Export the three before launching the agent, or set them in the environment that actually runs the helper; restart the agent after changing them. Per-host wiring (Manus connector, Codex env policy, Windows paths) is in [`HOSTS.md`](HOSTS.md).

### Secrets

The key lives only in the environment. `--check-config` is the sole way to inspect configuration; it reports presence, never values. When a variable is missing, name it and ask for secure configuration through the host. A key the user has asked to rotate is retired.

## Offline tests

```bash
uv run --with openai --with Pillow python -m unittest discover -s "$SKILL_DIR/tests" -v
# or, with the selected interpreter:
python3 -m unittest discover -s "$SKILL_DIR/tests" -v
```

Dummy configuration and mocked API calls; no provider contact, no charges.
