# AGENTS.md

## Workspace Defaults
- Follow `/home/ryan/Documents/agent_context/CLI_TUI_STYLE_GUIDE.md` for CLI taste and help shape.
- Follow `/home/ryan/Documents/agent_context/CANONICAL_REFERENCE_IMPLEMENTATION_FOR_CLI_AND_TUI_APPS.md` for launcher, installer, version, upgrade, and release behavior.

## Mission
Keep `whatsapp` as a small CLI that sends WhatsApp messages through the user's existing Chromium or WhatsApp Web session.

## Product Boundaries
- Do not turn this into a full WhatsApp client.
- Prefer reusing an existing browser session over managing a separate long-lived browser profile.
- Background sends should record inspectable job state and emit completion/failure notifications through the Quickshell bar, with `notify-send` only as a fallback.

## Implementation Rules
- Keep the command surface compact and explicit.
- Preserve `-h`, `-v`, `-u`, and `conf` behavior through the shared CLI contract.
- Do not print message contents beyond the short status/job surfaces already exposed by the app.
