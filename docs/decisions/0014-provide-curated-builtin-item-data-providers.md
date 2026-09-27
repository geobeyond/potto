---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Provide a curated list of built-in collection item data providers

## Context and Problem Statement

Item data providers are pluggable ([ADR-providers]), but pluggability alone doesn't tell users which data sources
actually work. pygeoapi's experience shows the downside of a very open provider ecosystem: many providers of
varying quality and maintenance status, inconsistent support for features like CQL2 or CRS transformation, and
users who can't tell which ones are safe to rely on.

potto also accepts provider configuration from collection descriptions, which may be edited by non-admin users.
Loading arbitrary code named in such a description would be a security risk.

Which item data providers should potto offer, and how can new ones be added?

## Considered Options

- A curated set of built-in providers maintained with potto, extensible only by programmatic registration
- An open plugin system via Python entry points, discovered automatically
- Allow collection descriptions to reference providers by dotted import path, as pygeoapi does
- Rely on pygeoapi's provider ecosystem as the primary source of providers

## Decision Outcome

Chosen option: "A curated set of built-in providers maintained with potto", because it gives users a small set of
providers that are known to work, are tested together and are held to the same quality bar, and it ensures that
collection descriptions can only select from vetted code, never load new code.

The design:

- potto ships these feature providers, registered at import time in `providers/features/__init__.py`:
  - `postgis`: features from a PostGIS table, via SQLAlchemy;
  - `pyogrio`: any OGR-readable file or source (GeoPackage, Shapefile, FlatGeobuf, ...);
  - `duckdb`: tabular/geospatial files (e.g. GeoParquet, CSV) queried with DuckDB;
  - `collection-config`: small datasets stored inline in the collection's own configuration;
  - `pygeoapi`: a compatibility bridge that runs an existing pygeoapi provider, for sources potto doesn't cover
    natively;
- Collections refer to a provider by its registered name only. Unknown names are an error;
- Extending the list is possible, but deliberate: code running inside potto calls `register_feature_provider(name,
  factory)`. There is no automatic discovery through entry points;
- New built-in providers are expected to support the full `FeatureProviderProtocol`
  ([ADR-feature-provider]) and to come with tests.

<!-- TODO: define minimum requirements for a built-in provider (e.g. CQL2 support, CRS transformation, test coverage),
and decide whether an entry-point based opt-in (enabled by an admin setting) should be added later. -->

### Consequences

- Good, because users get a small, dependable set of providers covering the most common data sources;
- Good, because collection descriptions can't load arbitrary code;
- Good, because the pygeoapi bridge keeps the long tail of pygeoapi providers reachable;
- Bad, because potto maintainers take on the maintenance of every built-in provider and its dependencies (pyogrio,
  DuckDB, ...);
- Bad, because third parties can't ship a provider as a separate package that "just works" after installation;
- Bad, because features provided through the pygeoapi bridge are limited to what pygeoapi supports (e.g. no
  cql2-text).


[ADR-providers]: 0012-mediate-collection-item-data-via-pluggable-providers.md
[ADR-feature-provider]: 0013-feature-collection-item-provider-protocol.md
