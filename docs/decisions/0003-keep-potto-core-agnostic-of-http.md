---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Keep potto's core agnostic of HTTP

## Context and Problem Statement

One of potto's founding ideas (see `docs/motivation.md`) is a clean split of responsibilities: vanilla pygeoapi
tries to be both a geospatial library and a web framework, supporting flask, starlette and django at once, which
results in a complex codebase. potto instead wants the geospatial and domain logic to know nothing about the web, and
lets the web framework (starlette + FastAPI) handle the "webby" parts of OGC APIs: HTML rendering, link generation,
content negotiation, compression and the OpenAPI document.

The same domain logic is also used by non-HTTP entry points: the CLI (`cliapp/`), the admin UI, background workers
([ADR-events]) and tests. If the core depended on HTTP request objects, each of these would have to fake a request.

Where should the boundary between potto's domain core and its HTTP layer be, and what may cross it?

## Considered Options

- An HTTP-agnostic core (managers, operations, providers, schemas, authz) with all HTTP concerns in `webapp/`
- Let core code accept and inspect framework `Request` objects where convenient
- Follow pygeoapi's model, where the core API class handles requests and responses in a framework-neutral
  request/response abstraction

## Decision Outcome

Chosen option: "An HTTP-agnostic core with all HTTP concerns in `webapp/`", because it keeps the domain logic
reusable from the CLI, the admin UI, workers and tests, and lets the web layer use its framework's features fully
instead of working through a lowest-common-denominator abstraction.

The design:

- The core (`managers/`, `operations/`, `providers/`, `authz/`, `exceptions.py`, and the `wrapper.Potto` facade)
  takes and returns plain python values and `schemas.*` objects, never `Request`/`Response` objects;
- Callers identify themselves with a `PottoUser | None`, not with a request. Non-HTTP callers use synthetic users such
  as the CLI system user (`cliapp/_shared.py::get_cli_system_user()`);
- Core exceptions (`PottoNotFoundException`, `PottoBadRequestException`, `PottoCannotXxxException`,
  `CapabilityNotSupported`, ...) carry no HTTP status codes. The web layer maps them in exception handlers
  (`webapp/api/main.py`) and admin views (`_PottoAdminModelView.handle_exception()`);
- Link generation is done by the web layer. Schemas that need links receive a `UrlResolver`
  (`webapp/protocols.py`) instead of building URLs themselves, e.g. `get_links(url_resolver)` in `schemas/web/`;
- HTML rendering (Jinja templates under `webapp/templates/`), the OpenAPI document (`webapp/api/`) and content
  negotiation all live in `webapp/`;
- pygeoapi is used only as a library of providers and helpers, never as a request handler.

### Consequences

- Good, because the same domain logic serves the API, the web UI, the admin UI, the CLI and workers without
  adaptation;
- Good, because the core is easy to unit test without spinning up an HTTP app;
- Good, because the web layer is free to use starlette/FastAPI idioms (dependencies, middleware, OpenAPI generation)
  directly;
- Bad, because every exception type and link must be explicitly mapped by the web layer, which is extra wiring;
- Bad, because the boundary must be actively defended. It is easy to let a starlette type slip into a schema.

Known leaks to resolve or explicitly accept:

<!-- TODO: decide, for each of these, whether to fix it or record it as an accepted exception -->

- `schemas/auth.py::PottoUser` subclasses starlette's `BaseUser`, and its `__admin_repr__` takes a `Request`;
- `schemas/base.py` and `schemas/features.py` use starlette's `QueryParams`;
- `managers/postgis/manager.py` imports starlette-admin's `BaseModelView` at runtime, and
  `managers/postgis/db/models.py` imports `Request`;
- `config.py` depends on `starlette_babel`.


[ADR-events]: 0016-adopt-event-driven-architecture.md
