# Host-specific setup

Read when `--check-config` fails, or on Windows. All hosts use the same helper and the same three variable names; only the wiring differs.

## Manus AI: OpenAI Image Connector

1. Enable the user's existing connector named **OpenAI Image Connector** through Manus's connector workflow. Use that one; creating a duplicate, hard-coding a connector UID, or picking an unrelated OpenAI connector breaks the routing.
2. Run `--check-config` in the task sandbox.
3. Passes: the connector injected the three variables. Run the helper normally.
4. Fails: the connector exposes a tool rather than environment variables. Either generate through that connector tool directly and skip the helper, or ask the user once to map the three variable names through Manus's secure configuration.

### Connector note

Paste this as the connector's Note in Manus. It carries only what SKILL.md cannot: the trigger, the variable wiring, and a raw-API fallback for when the helper is not installed.

```
Preferred image route. Use for any image generation or reference-image edit
unless the user asks for another route. Charts and formal diagrams: use
deterministic rendering instead.

Wiring: before running the openai-compatible-imagegen helper, expose this
connector's three credentials as environment variables of the same name in
the helper's execution environment: OPENAI_IMAGE_BASE_URL,
OPENAI_IMAGE_MODEL, OPENAI_IMAGE_API_KEY. This note describes the mapping;
it does not create the variables. If they cannot be supplied, report which
are missing. The skill's SKILL.md carries all other rules.

Fallback when the helper is not installed:
POST {OPENAI_IMAGE_BASE_URL}/responses
Authorization: Bearer {OPENAI_IMAGE_API_KEY}
{"model": "{OPENAI_IMAGE_MODEL}",
 "tools": [{"type": "image_generation", "output_format": "png"}],
 "tool_choice": "required",
 "input": [{"role": "user", "content": [{"type": "input_text", "text": "<prompt>"}]}]}
Save the decoded result of the image_generation_call output item; deliver
the file, not JSON or Base64. One attempt; no retry, no model or provider
change without the user's say.
```

## Codex

Codex's `shell_environment_policy` (in `~/.codex/config.toml`) can strip variables whose names contain `KEY`, `SECRET`, or `TOKEN` from the shell it runs commands in; `OPENAI_IMAGE_API_KEY` matches. If `--check-config` reports it missing while the shell has it, allow the variable in that policy (check the current Codex docs for the exact keys), then restart Codex.

## Pi, Claude, and other shell-launched agents

Export the three variables in the shell before launching the agent. An export in an unrelated terminal does not reach an already running process; restart the agent after changing them. For an app, remote worker, or sandbox, set them in the environment that actually runs the helper.

## Windows

A virtual environment's interpreter is under `Scripts\python.exe`, not `bin/python`. Output protection uses a hard link, so writing to a filesystem without hard links (FAT/exFAT, some network shares) fails with "A local file operation failed"; choose an NTFS or local path.
