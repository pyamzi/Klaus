# MCP is served remotely from klaus.ink only

Klaus exposes the user's Materials and Cards over MCP from klaus.ink, behind the Klaus Account subscription, and deliberately does not also run a local MCP server. Klaus is for ordinary users, who connect assistants like claude.ai to a URL; almost nobody wires up a local MCP server, so one would be maintenance without users. Remote MCP depends on Material sync to klaus.ink. Klaus's own use of Claude Code / Codex CLI as an assistant provider is separate and does not use MCP.

The app is free (it is AGPL, ADR-0001); the Klaus Account subscription pays for what klaus.ink hosts: Material sync, remote MCP, and later Collection sync.
