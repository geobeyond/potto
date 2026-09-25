---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Allow the admin UI to be turned off

## Context and Problem Statement

potto includes an admin UI, built with starlette-admin, where managers contribute views for collections, processes,
server metadata and user accounts. It is useful for many deployments, but not all:

- deployments that manage everything through the API, the CLI or infrastructure-as-code have no use for it;
- read-only deployments (e.g. the configuration file manager) gain little from an admin that can't edit anything;
- security-conscious deployments want to minimise their attack surface, and an admin login page on the public
  internet is an obvious target;
- some deployments may want to run the admin on a separate, internal-only instance.

Today the admin app is always mounted (`webapp/main.py`, `create_admin_app_from_settings`).

Should the admin UI be optional, and how should it be controlled?

## Considered Options

- A setting that enables or disables the admin UI, enabled by default
- A setting that enables or disables the admin UI, disabled by default
- Always mount the admin UI, and rely on authorization to protect it
- Ship the admin UI as a separate package/app

## Decision Outcome

Chosen option: "A setting that enables or disables the admin UI, enabled by default", because it keeps the current
out-of-the-box experience while letting deployments remove the admin UI entirely, rather than merely protecting it.

The design:

- A new boolean setting (e.g. `PottoSettings.enable_admin_ui`, env var `POTTO__ENABLE_ADMIN_UI`) controls whether the
  admin app is created and mounted;
- When disabled, no admin routes, templates or static files are served, and managers' `get_<x>_admin_view()` methods
  are not called;
- Links to the admin UI (e.g. from the web UI's navigation) are hidden when it is disabled;
- Disabling the admin UI does not disable any functionality: everything it does is also available through the API
  or the CLI.

<!-- TODO: confirm the setting name, and whether a configurable mount path is also wanted (e.g. to serve the admin
under an obscure or internal-only path). -->

### Consequences

- Good, because deployments can reduce their attack surface and resource usage;
- Good, because it allows split deployments (a public instance without admin, an internal one with it);
- Bad, because it adds a configuration branch that must be tested (e.g. no template or link should assume the admin
  is present);
- Bad, because operators who disable it depend on the API and CLI covering every admin task.
