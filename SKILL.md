---
name: openai-compatible-imagegen
description: "Generate and edit images through the user's configured OpenAI-compatible Responses API. Use for illustrations, posters, product visuals, UI mockups, character art, and semantic image edits. Prefer this route when OPENAI_IMAGE_BASE_URL, OPENAI_IMAGE_MODEL, and OPENAI_IMAGE_API_KEY are supplied by a connector or the agent's environment."
---

# OpenAI-Compatible Image Generation

## Purpose

Use the user's configured endpoint as the preferred image-generation route. Their provider supports `gpt-6-astra` with the Responses API `image_generation` tool under the hood. This is a provider-specific capability, not a promise that every OpenAI-compatible service supports it. Use `OPENAI_IMAGE_MODEL` as configured; do not substitute `gpt-image-2` or silently switch models.

Preserve the user's medium, composition, aspect ratio, transparency, wording, references, and edit constraints. Choose sensible defaults for nonessential details. Do not ask the user to repeat an already configured routing preference or prompt.

## Configuration: environment only

The helper requires all three variables. It does not load `.env` files, infer an endpoint, or fall back to generic OpenAI credentials.

| Variable | Meaning |
| --- | --- |
| `OPENAI_IMAGE_BASE_URL` | Explicit HTTPS API base URL, normally ending in `/v1`, not `/responses` |
| `OPENAI_IMAGE_MODEL` | Provider model; set to `gpt-6-astra` for the user's current service |
| `OPENAI_IMAGE_API_KEY` | Credential belonging to that endpoint |

The URL must not contain credentials, query parameters, or fragments. `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_API_BASE` are deliberately ignored to avoid mixing credentials from unrelated services.

### Manus AI: OpenAI Image Connector

1. Enable the user's existing connector named **OpenAI Image Connector** through Manus's connector workflow. Do not create a duplicate, hard-code a connector UID, or substitute an unrelated OpenAI connector.
2. Run the helper with `--check-config` in the task sandbox.
3. If it passes, the connector injected the three `OPENAI_IMAGE_*` variables into the sandbox. Run the helper normally.
4. If it reports missing variables, the connector exposes a tool rather than environment variables. Generate through that connector tool directly and skip the helper, or ask the user once to map the three variable names through Manus's secure configuration. Never ask for the key in chat.

### Pi, Codex, Claude, and other agents: launching environment

The helper inherits the three variables from its parent process. For a shell-launched agent, export them before launching the agent. For an app, remote worker, or sandbox, configure them in the environment that actually runs the helper; an export in an unrelated terminal will not update an already running process. Restart the agent/task when necessary after changing its environment.

Use the same helper and variable names on every host. No host detection or credential fallback is needed.

Codex note: Codex's `shell_environment_policy` can strip variables whose names contain `KEY`, `SECRET`, or `TOKEN` (when `ignore_default_excludes = false`, or `inherit` is `"core"` or `"none"`). `OPENAI_IMAGE_API_KEY` matches. If `--check-config` reports it missing while the shell has it, fix `~/.codex/config.toml`, not the skill.

### Secret handling

Never put the real key in a prompt, skill file, source file, command argument, shell-history entry, log, attachment, or final response. Do not use `env`, `printenv`, shell tracing, or commands that display the variables' values. If configuration is missing, identify the missing variable names and ask for secure configuration, not for a key pasted into chat. Do not reuse a key the user has asked to rotate.

## Setup and preflight

Requirements: Python 3.10+, `openai`, and `Pillow`. The script declares them inline (PEP 723) and `requirements.txt` lists the same pins. Resolve `SKILL_DIR` to this skill's actual directory from its loaded path/metadata. Do not assume `/home/ubuntu`, a particular agent installation directory, or the current working directory.

Preferred when `uv` is available; it resolves and caches the dependencies itself:

```bash
# SKILL_DIR is the actual directory containing this SKILL.md.
uv run "$SKILL_DIR/scripts/generate_image.py" --check-config
```

Without `uv`: use an existing Python environment that already has the dependencies, or create one in a writable location following the host's installation and network-approval rules:

```bash
python3 -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/python" -m pip install -r "$SKILL_DIR/requirements.txt"
"$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/generate_image.py" --check-config
```

On Windows a virtual environment's interpreter is under `Scripts/python.exe`. Use the same launcher (`uv run ...` or the selected interpreter) for every helper call; the examples below write `python3` for brevity. `--check-config` works without the optional packages installed; it reports only configuration presence and URL structure. It does not authenticate or make a network request.

## Generation workflow

1. **Classify the request.** Use this skill for visual assets and semantic image edits. Use deterministic rendering instead for exact charts, numeric plots, formal diagrams, or exact node relationships.
2. **Prepare the prompt.** Keep the user's intent and required wording. Add framing, lighting, palette, material, and exclusions only when helpful. For edits, explicitly state what must stay unchanged; generative edits do not guarantee pixel-perfect preservation.
3. **Select output and controls.** Choose a writable workspace output path. The extension selects PNG, JPEG, or WebP. Pass explicit size, background, and quality controls when requested and supported. The helper supports the standard sizes below; for other ratios, describe the desired framing and disclose any approximation rather than promising an exact size.
4. **Run the bundled helper.** It sends the configured model to `/responses`, declares the `image_generation` tool, and requires tool use. Do not rewrite API or Base64 extraction code for ordinary generation or reference-image requests.
5. **Validate visually.** The helper checks Base64 and decodability before saving. A size or format mismatch, or more than one image call, is still saved but reported as an `IMAGE_GENERATION_WARNING:` line on stderr; read stderr and disclose the deviation. On success the helper prints a `Revised prompt:` line when the orchestrating model rewrote the prompt; compare it against required wording. Open the resulting image with the host's image-viewing capability to check required wording, composition, and edit constraints. If visual inspection is unavailable, say so; do not claim it was performed. Avoid endless subjective refinement.
6. **Deliver the artifact.** Attach or expose the generated file using the host's supported artifact mechanism. If attachments are unavailable, provide the output path. Identify the configured model and say the compatible endpoint was used. Do not deliver raw response JSON, Base64, or credentials.

### New image

Using the selected Python interpreter (`python3` here):

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

`--image` accepts local PNG, JPEG, or WebP files up to 20 MiB each and may be repeated. The helper validates and sends them as `input_image` data URLs to the configured provider. Add `--input-fidelity high` when faces, logos, or fine details must survive the edit. Only send references authorized for that provider. Mask-based editing is not implemented.

### Helper controls

- `--output PATH`: default `generated_image.png`; `.png`, `.jpg`, `.jpeg`, or `.webp` selects the requested format.
- `--size`: `auto`, `1024x1024`, `1536x1024`, or `1024x1536`.
- `--background`: `auto`, `opaque`, or `transparent`; transparency requires PNG or WebP.
- `--quality`: `auto`, `low`, `medium`, or `high`.
- `--input-fidelity`: `high` or `low`; requires `--image`. `high` preserves reference details more closely.
- `--timeout SECONDS`: positive SDK request timeout; default 300 seconds, not a guaranteed total wall-clock deadline.
- `--overwrite`: explicitly allow replacing an existing output; without this flag existing files are protected.
- `--check-config`: offline configuration validation; no prompt required.

Size, background, quality, and input fidelity are omitted from the API request unless supplied. Optional controls depend on provider support. Do not silently remove a user-required control if the endpoint rejects it. The helper handles one synchronous image result per invocation, with automatic SDK retries disabled to reduce duplicate paid requests. It does not poll asynchronous responses or switch providers.

## Failure handling and fallback

- **Missing configuration:** stop before making a request; use the relevant connector or launching-environment setup above. Ask once for secure configuration, never the secret itself.
- **Authentication or permissions:** stop and report the safe error category. Do not retry repeatedly or dump upstream error bodies.
- **Model, endpoint, or tool unsupported:** check configured settings and provider documentation through available approved tools. Change the model only with user authorization; do not assume `gpt-6-astra` exists on other services.
- **Rate limit, timeout, connection failure, or server error:** do not automatically resubmit. The original request may have been accepted and may still incur a charge. Explain the uncertainty before another attempt.
- **Pending response:** the helper does not poll. Follow the provider's documented retrieval workflow if available and authorized, rather than starting another generation. Do not invent a polling protocol or print entire responses to diagnose it.
- **Text-only, failed, empty, or malformed image output:** report that no valid artifact was saved. For a text-only response the error includes a short `Model text:` excerpt (often a refusal); relay it. A text-only response does not prove the provider can never generate images.
- **Alternative route:** use a different provider or built-in image tool only if it is actually available and the user has already permitted that fallback or approves it now. Preserve the prompt, disclose the switch, and consider reference-image privacy and cost. If no approved fallback exists, stop with a concise explanation.

Do not use this skill for audio, video, or unrelated text generation.

## Offline helper tests

With the dependencies installed in the selected Python environment:

```bash
uv run --with openai --with Pillow python -m unittest discover -s "$SKILL_DIR/tests" -v
# or, with the selected interpreter:
python3 -m unittest discover -s "$SKILL_DIR/tests" -v
```

Tests use dummy configuration and mocked API calls; they do not contact the provider or incur generation charges.
