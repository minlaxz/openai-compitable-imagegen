# openai-compatible-imagegen

An agent skill that generates and edits images through **your own OpenAI-compatible endpoint** instead of the agent's built-in (credit-metered) image tool.

Built for [Manus](https://manus.im), but works with any agent that can run a Python script and read environment variables (Claude Code, Codex, Pi, OpenClaw, etc.).

## Why

Free or credit-limited AI agents charge credits for every image they generate. If you already pay for an OpenAI Plus or Pro subscription, you can route image generation through an OpenAI-compatible proxy such as 9router (or any similar gateway) and have the agent call *that* instead. The agent keeps its credits; your subscription does the work.

The skill ships a single helper script that sends the prompt to `POST {BASE_URL}/responses` with the `image_generation` tool, validates the returned image, saves it as PNG, JPEG, or WebP, and refuses to run without explicit configuration so it never silently bills the wrong account.

## Requirements

- Python 3.10+
- An OpenAI-compatible endpoint that supports the Responses API with the `image_generation` tool (9router with a ChatGPT Plus/Pro login works; plain OpenAI works too)
- The `openai` and `Pillow` packages (installed automatically with `uv run`, or via `requirements.txt`)

## Configuration

The helper reads **exactly three** environment variables. It ignores `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, and `.env` files on purpose, so credentials from unrelated tools never get mixed in.

| Variable | Example | Notes |
| --- | --- | --- |
| `OPENAI_IMAGE_BASE_URL` | `https://your-router.example.com/v1` | HTTPS, ends in `/v1`, no `/responses` suffix, no query string or credentials |
| `OPENAI_IMAGE_MODEL` | `gpt-6-astra` | Whatever model name your provider exposes for image generation |
| `OPENAI_IMAGE_API_KEY` | `sk-...` | The key for *that* endpoint |

Export them in the shell **before** starting the agent; the helper inherits them from the parent process:

```bash
export OPENAI_IMAGE_BASE_URL="https://your-router.example.com/v1"
export OPENAI_IMAGE_MODEL="gpt-6-astra"
export OPENAI_IMAGE_API_KEY="sk-..."
claude   # or codex, pi, ...
```

For a persistent setup, put the exports in `~/.zshrc` / `~/.bashrc`, or in the agent's own env config (for Claude Code: `env` in `~/.claude/settings.json`). Manus connector setup, the Codex env-policy gotcha, and Windows notes are in [`HOSTS.md`](HOSTS.md).

Check the config without making a network call:

```bash
uv run scripts/generate_image.py --check-config
```

## Installation

Copy or clone this directory into your agent's skills folder:

| Agent | Path |
| --- | --- |
| Claude Code | `~/.claude/skills/openai-compatible-imagegen/` |
| Codex | `~/.codex/skills/openai-compatible-imagegen/` |
| Manus | upload via the Skills UI |

The agent reads `SKILL.md` for instructions and runs `scripts/generate_image.py`.

## Usage

Preferred launcher is `uv`, which resolves the inline PEP 723 dependencies:

```bash
uv run scripts/generate_image.py \
  --output ./artifacts/poster.png \
  --size 1024x1536 \
  -- "A portrait-format travel poster with the exact title: NIGHT TRAIN"
```

Without `uv`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/generate_image.py --output out.png -- "a red bicycle on a white background"
```

Edit an existing image (semantic edit; mask-based editing is not implemented):

```bash
uv run scripts/generate_image.py \
  --image ./reference.png \
  --input-fidelity high \
  --output ./artifacts/edited.png \
  -- "Change only the jacket to dark green. Preserve the face, pose, and background."
```

All flags and their allowed values: `uv run scripts/generate_image.py --help`. Optional controls are left out of the request unless you pass them, so providers that do not support them are not broken by defaults.

## Behavior worth knowing

- **One request, no retries.** SDK auto-retries are disabled so a flaky network cannot double-bill you. On a timeout or 5xx, the original request may still have been accepted; decide manually before resubmitting.
- **Mismatches are kept, not discarded.** If the provider returns a different size or format than requested, the image is still saved and an `IMAGE_GENERATION_WARNING:` line goes to stderr. You paid for it; you keep it.
- **Existing files are protected.** Pass `--overwrite` to replace.
- **Revised prompts are surfaced.** If the model rewrote your prompt, the script prints a `Revised prompt:` line so you can check required wording survived.
- **Text-only responses fail loudly.** A refusal or text answer produces an error with a short `Model text:` excerpt instead of an empty file.
- **Secrets never hit the output.** Errors are reduced to safe categories plus the HTTP status and the provider's structured error code; upstream message bodies and keys are not echoed.

## Tests

Offline, mocked, no charges:

```bash
uv run --with openai --with Pillow python -m unittest discover -s tests -v
```

## Layout

```
SKILL.md                  # instructions the agent reads
HOSTS.md                  # per-host setup (Manus, Codex, Windows), read on demand
scripts/generate_image.py # the helper (PEP 723 inline deps)
tests/                    # unit tests with mocked API
requirements.txt          # same pins as the inline metadata
```
