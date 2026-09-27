---
icon: lucide/heart
---

# Motivation

This project started out as a [pygeoapi]-powered web application written with starlette and
FastAPI. The intention was to showcase using pygeoapi as a library and build an external shell to it using some
different ideas:

- Add concepts of resource ownership, sharing and resource visibility on to the main model of the system;
- Avoid leaking web-related concepts into the core model;
- Enforce strict contracts between components by using typed data structures;
- Use structural subtyping rather than inheritance as the extensibility mechanism;
- Focus on async patterns.

The fact that pygeoapi offered builtin support for all of starlette, flask and django was also something we thought
to invert - We wanted something which could be wrapped by any external web framework, not the other way around. This
would mean that:

- The external web framework only ever calls a potto core function, and never the other way around;
- potto core does not deal with 'webby' concepts at all - no requests, no headers, no status codes, etc. potto's logic
  gets translated to/from a respective web concept by the external web framework;
- The external web framework can be used to its fullest instead of having to use a least common denominator;
- potto can be used in different contexts too, outside of the web;

As development started, it became apparent that these ideas would not be possible to implement cleanly while
keeping a pygeoapi engine as a requirement. As such, we decided to start afresh and build something from the ground up.

!!! success ":heart: pygeoapi"

    We still love pygeoapi, but wanted to take a different direction with potto.

Regardless, and because potto still needs a default web framework in order to be usable, we chose to go
with [starlette] and [FastAPI]. But a downstream application could very easily just use potto core with any other
web framework and provide the respective glue code.


### OGC API compliance notes

Potto means to present a single OGC API compliant landing page under `/api/` with the main media type of responses
being of the JSON family. It also comes with a web UI under `/` - however, **the web UI is intentionally not OGC
API compliant**. The reason being that with are of the opinion that replicating all OGC API path operations in
a UI results in an overly complicated user experience.


## Name inspiration

This project's name is a hommage to the cute [potto mammal], which inhabits the rainforests of tropical Africa.

[FastAPI]: https://fastapi.tiangolo.com/
[potto mammal]: https://en.wikipedia.org/wiki/Potto
[pygeoapi]: https://pygeoapi.io/
[starlette]: https://starlette.dev/
