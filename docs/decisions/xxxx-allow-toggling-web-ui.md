---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Allow the web UI to be turned off

## Context and Problem Statement

potto serves two user-facing surfaces: an OGC API under `/api/` (JSON-first, OGC compliant) and a web UI under `/`,
rendered with Jinja. As explained in `docs/motivation.md`, the web UI is intentionally *not* OGC API compliant: it
doesn't try to replicate every OGC API operation as HTML, favouring a simpler user experience instead.

Some deployments only need the API: potto may sit behind another portal, catalogue or custom frontend, or be used
purely machine-to-machine. For them, the web UI (landing page, language selection, feature browsing pages) is
unnecessary surface to maintain, secure and brand. Today its routes are always registered (`webapp/main.py`).

Should the web UI be optional, and how should it be controlled?

## Considered Options

- A setting that enables or disables the web UI, enabled by default
- Always serve the web UI
- Split the web UI into a separate application that consumes potto's API

## Decision Outcome

Chosen option: "A setting that enables or disables the web UI, enabled by default", because it keeps the default
experience friendly for humans, while letting API-only deployments drop the HTML surface completely.

The design:

- A new boolean setting (e.g. `PottoSettings.enable_web_ui`, env var `POTTO__ENABLE_WEB_UI`) controls whether the
  web UI routes (landing page, set-language and the HTML OGC API pages under `webapp/routes/`) and their static files
  are registered;
- The OGC API under `/api/` is unaffected. Its HTML representations, if any, are part of the API and controlled
  separately;
- When the web UI is disabled, `/` redirects to the API landing page (`/api/`), so the root URL still leads somewhere
  useful;
- Authentication routes that the API or the admin UI need (e.g. the OIDC login/callback) stay available regardless.

<!-- TODO: confirm the setting name, the behaviour of `/` when disabled (redirect vs 404), and whether the admin UI
link should still be reachable when the web UI is disabled (see the admin UI toggle ADR). -->

### Consequences

- Good, because API-only deployments serve less and have less to secure and maintain;
- Good, because potto becomes easier to embed behind a custom frontend;
- Bad, because shared pieces (auth routes, static files, templates used by both UIs) must be carefully separated so
  that disabling one surface doesn't break another;
- Bad, because it adds a configuration branch that must be tested.
