---
name: project-intake
description: Start a project idea through the corporate CEO workflow.
---

Use the `corporate-project` skill. This harness checkout creates corporate
folders; it is not itself the product corporate root.

Before DESIGN:

1. Create a dedicated corporate folder (sibling to harness/site — never nested).
2. `corp-harness init --root <corporate-folder> --site <app-checkout> …`
3. `program_id` may differ from site `site_id`.
4. Ask the user to open the corporate folder as this chat's workspace before
   DESIGN. Never `move_agent_to_root` from the factory checkout into that
   folder or later from corporate into the site.

Invoke `corporate-ceo` and stop before implementation until corporate acceptance
and handoff are recorded.
