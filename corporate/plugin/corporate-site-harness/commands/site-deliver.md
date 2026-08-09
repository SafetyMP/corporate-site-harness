---
name: site-deliver
description: Execute an approved corporate handoff in the active site repository.
---

Resolve `program.site_path`, call `move_agent_to_root` to it, and confirm the
active workspace root matches before any site work. If the switch fails or the
root is still not `site_path`, stop and ask the user to open/switch that
workspace manually; do not continue from the corporate/factory root.

Use the `site-delivery` skill from the site root. Invoke `site-manager`, dispatch bounded
ADR packets to `site-specialist`, rerun the site oracle after integration, and obtain an
independent `operations-excellence` verdict.

Stay inside `program.site_path`. Product site delivery must not edit factory
`src/corp_harness/**` or factory plugin sources.
