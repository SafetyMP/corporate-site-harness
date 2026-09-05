---
name: corporate-project
description: Runs corporate intake, specialist design, COO acceptance, conformance review, and CEO packaging for a new project idea or active program.
---

# Corporate project

## Roles of roots

- **This Cursor Harness checkout** is the factory/tooling workspace used to
  *create* corporate folders. It owns platform surfaces such as
  `corp-harness portfolio`. It is not the corporate program root for a product.
- **Corporate folder** (`--root`): a dedicated workspace (its own directory /
  git root) that holds `program.json`, specs, gates, and evidence. Create it
  with `create_project` or `mkdir` + git init, then `corp-harness init`.
- **Site** (`--site`): the application checkout the corporate folder points at
  (e.g. HR ERP). Never put `program.json` in the site.
- **`program_kind`**: `product` (default) targets an app site; `factory`
  targets this harness checkout as the implementation root for platform work.

Each corporate folder points at exactly one site via `site_path`.
`program_id` may differ from site `site_id` (e.g. `core-hr` vs `hr-erp`).

## Bootstrap (before DESIGN)

1. Confirm the site path (existing app vs greenfield site), or factory root for
   `--kind factory`.
2. Create a **new corporate folder** separate from product sites and from the
   factory checkout (e.g. `~/work/my-app-corporate` sibling to the site).
   Never nest `--root` under `--site`
   (including `<factory>/programs/<id>`). Prefer its own git root and its own
   Cursor workspace. Never call `move_agent_to_root` across corporate and site.
3. `corp-harness init --root <corporate-folder> --id <program_id> --site <site>
   [--kind product|factory] …` (dry-run first; `--apply` per policy / user
   confirmation). Nested roots are rejected for every `program_kind`.
4. For **factory** programs: after `master_spec` is recorded, stop until the
   user records `factory_authorization` (`--actor user`). Do not advance to
   `CORPORATE_ACCEPTANCE` without it. Agents never pass `--actor user`.
5. Corporate phases run in a chat whose workspace **already is** the corporate
   folder. Site delivery runs in a **different** chat whose workspace already
   is `site_path`. If this chat is the wrong plane: **stop** and ask the user
   to open the other folder. Do not stash or fast-forward the other git root.

## Flow

1. Run `corp-harness status --root <corporate-folder>`; never infer state from chat.
2. In `DESIGN`, invoke the CEO and only the necessary domain specialists.
3. Record the master spec and acceptance artifacts, then advance with the CLI.
4. Invoke the COO for executable gates, separate KPIs, and the site handoff
   (`site_id` must match the site manifest when present).
5. After site verification, invoke assigned specialists for conformance.
6. Invoke the adversary only after conformance passes.
7. Let the CEO prepare the dossier; stop at `AWAITING_USER_APPROVAL`.
