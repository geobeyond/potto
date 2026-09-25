---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Keep potto's core agnostic of HTTP

## Context and Problem Statement

One of potto's founding ideas is a clean split of responsibilities. The geospatial and domain logic know nothing
about the web. The outer layer can then use a web framework ([starlette] + [FastAPI]) to handle the "webby" parts
of OGC APIs: HTML rendering, link generation, content negotiation, compression and the OpenAPI document.

The same domain logic can also used by non-HTTP entry points: a CLI, an admin UI, background workers
([ADR-events]), etc. If the core depended on HTTP request objects, each of these would have to fake a request.

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

- The core takes and returns plain python values and `schemas.*` objects, never `Request`/`Response` objects;
- Callers identify themselves with a `PottoUser | None`, not with a request;
- Core exceptions carry no HTTP status codes. The web layer maps them in exception handlers;
- Link generation is done by the web layer. Schemas that need links receive a `UrlResolver`
  instead of building URLs themselves, e.g. `get_links(url_resolver)` in `schemas/web/`;
- HTML rendering, the OpenAPI document and content negotiation all live in `webapp/`;

### Consequences

- Good, because the same domain logic serves the API, the web UI, the admin UI, the CLI and workers without
  adaptation;
- Good, because the core is easy to unit test without spinning up an HTTP app;
- Good, because the web layer is free to use starlette/FastAPI idioms (dependencies, middleware, OpenAPI generation)
  directly;
- Bad, because every exception type and link must be explicitly mapped by the web layer, which is extra wiring;
- Bad, because the boundary must be actively defended. It is easy to let a starlette type slip into a schema.

Known leaks that are explicitly accepted:

- `schemas/auth.py::PottoUser` subclasses starlette's `BaseUser`, and its `__admin_repr__` takes
   a `Request`;
- `schemas/base.py` and `schemas/features.py` use starlette's `QueryParams`;
- `managers/postgis/manager.py` imports starlette-admin's `BaseModelView` at runtime, and
  `managers/postgis/db/models.py` imports `Request`;
- `config.py` depends on `starlette_babel`.


[ADR-events]: 0016-adopt-event-driven-architecture.md
[FastAPI]: https://fastapi.tiangolo.com/
[starlette]: https://starlette.dev/
