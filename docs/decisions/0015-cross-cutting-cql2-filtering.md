---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Use OGC CQL2 as the cross-cutting language for filtering resource and item listings

## Context and Problem Statement

potto lists many things: collections, processes, jobs, users (through their managers) and collection items (through
providers). Each listing needs filtering, and today each one has its own ad hoc filter dataclass (`CollectionFilter`,
`ProcessFilter`, `JobFilter`, `UserFilter`) with a few hardcoded dimensions such as identifier substrings.

OGC has standardized a filter language, Common Query Language 2 (CQL2), with text and JSON encodings. It is used by
OGC API – Features Part 3 (Filtering) for items, and by OGC API – Records for catalogue records. Collections and
processes are, in effect, catalogue records.

Which filtering language should potto use across its listings?

## Considered Options

- OGC CQL2 (text and JSON) as the single filter language for both resource listings and item listings, parsed with
  pygeofilter
- CQL2 for item listings only, and simple per-resource filter dataclasses for resource listings
- A potto-specific filter syntax
- Only the simple query parameters defined by each OGC API core (bbox, datetime, property=value)

## Decision Outcome

Chosen option: "OGC CQL2 as the single filter language for both resource listings and item listings", because it is
the OGC standard, clients only need to learn one language, and it prepares resource listings for OGC API – Records.

The design:

- Every listing endpoint that supports filtering accepts `filter` and `filter-lang` (`cql2-text` or `cql2-json`);
- CQL2 expressions are parsed once, in a shared place, into a [pygeofilter] AST, and invalid expressions are rejected
  with a `400` before reaching any manager or provider;
- The AST is passed down to the manager (for resource listings) or the provider (for item listings), bundled in their
  filter objects (e.g. `PottoFeatureFilter`, `CollectionFilter`). Each backend translates it to its own query
  language, e.g. to SQL with pygeofilter's SQLAlchemy backend, or evaluates it in memory with the native backend;
- Queryables are advertised per listing (`get_queryables()` on feature providers, and equivalent endpoints for
  resource listings), so clients know which properties they may filter on;
- CQL2 filters are always combined with authorization: a filter can only narrow the set of resources the user may
  already see, never widen it;
- Backends that can't support CQL2 must reject a filter explicitly, rather than silently ignoring it.

Current state:

- `PottoFeatureFilter` already accepts `filter`/`filter-lang`, but only the `pygeoapi` bridge provider forwards them,
  and the PostGIS provider only has a placeholder hook;
- Resource listings (`/collections`) don't accept a filter yet.

<!-- TODO: decide the conformance level to target (Basic CQL2 vs. advanced/spatial/temporal functions), and how
existing filter dataclass fields (e.g. identifiers) map onto CQL2 queryables. -->

### Consequences

- Good, because clients use one standard filter language everywhere in potto;
- Good, because it aligns resource listings with OGC API – Records and item listings with OGC API – Features Part 3;
- Good, because pygeofilter provides parsers and backends for SQL and in-memory evaluation, so most backends need
  little code;
- Bad, because every manager and provider has to implement or delegate CQL2 translation, and support will be uneven
  between backends at first;
- Bad, because CQL2 is expressive enough to produce expensive queries, so limits or timeouts may be needed;
- Bad, because it adds complexity to the manager and provider protocols compared with plain filter dataclasses.


[pygeofilter]: https://github.com/geopython/pygeofilter
