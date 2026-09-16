# Host-specific setup

Read when `--check-config` fails, or on Windows. All hosts use the same helper and the same three variable names; only the wiring differs.

## Manus AI: OpenAI Image Connector

1. Enable the user's existing connector named **OpenAI Image Connector** through Manus's connector workflow. Use that one; creating a duplicate, hard-coding a connector UID, or picking an unrelated OpenAI connector breaks the routing.
2. Run `--check-config` in the task sandbox.
3. Passes: the connector injected the three variables. Run the helper normally.
4. Fails: the connector exposes a tool rather than environment variables. Either generate through that connector tool directly and skip the helper, or ask the user once to map the three variable names through Manus's secure configuration.

## Codex

Codex's `shell_environment_policy` (in `~/.codex/config.toml`) can strip variables whose names contain `KEY`, `SECRET`, or `TOKEN` from the shell it runs commands in; `OPENAI_IMAGE_API_KEY` matches. If `--check-config` reports it missing while the shell has it, allow the variable in that policy (check the current Codex docs for the exact keys), then restart Codex.

## Pi, Claude, and other shell-launched agents

Export the three variables in the shell before launching the agent. An export in an unrelated terminal does not reach an already running process; restart the agent after changing them. For an app, remote worker, or sandbox, set them in the environment that actually runs the helper.

## Windows

A virtual environment's interpreter is under `Scripts\python.exe`, not `bin/python`. Output protection uses a hard link, so writing to a filesystem without hard links (FAT/exFAT, some network shares) fails with "A local file operation failed"; choose an NTFS or local path.
