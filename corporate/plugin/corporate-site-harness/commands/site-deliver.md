---
name: site-deliver
description: Execute an approved corporate handoff in the active site repository.
---

This command is for a chat whose workspace **already is** `program.site_path`.
Never call `move_agent_to_root` from a corporate folder into the site (Cursor
stashes the destination). If the active root is not `site_path`, stop and ask
the user to open that folder as its own workspace.

Use the `site-delivery` skill from the site root. Invoke `site-manager`, dispatch bounded
ADR packets to `site-specialist`, rerun the site oracle after integration, and obtain an
independent `operations-excellence` verdict.

Stay inside `program.site_path`. Product site delivery must not edit factory
`src/corp_harness/**` or factory plugin sources.
