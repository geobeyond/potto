---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define a feature provider protocol for feature collection items

## Context and Problem Statement

Feature collections are served according to OGC API – Features: items can be listed with paging, bbox, datetime,
property and CQL2 filters, fetched individually in a requested CRS, and described through a schema and a set of
queryables. The collection description also advertises spatial and temporal extents and a storage CRS.

Item data comes from pluggable providers ([ADR-providers]). pygeoapi's provider interface (`query()`/`get()`) is
synchronous, returns GeoJSON dicts, and mixes several concerns (paging, formatting, filtering) into a few
catch-all methods with many keyword arguments.

What contract should a feature data provider fulfil?

## Considered Options

- A potto-native, async `FeatureProviderProtocol` with one focused method per concern
- Reuse pygeoapi's feature provider interface as-is
- A minimal protocol exposing only listing and fetching, with extents, schema and queryables configured statically in
  the collection description

## Decision Outcome

Chosen option: "A potto-native, async `FeatureProviderProtocol`", because it matches potto's async-first design, gives
each OGC API – Features concern its own method, and uses potto's own schemas instead of loosely typed dicts.

The design:

- `providers/features/protocol.py::FeatureProviderProtocol` (`@runtime_checkable`) defines async methods:
  - `list_features(feature_filter)` and `count_items(feature_filter)`: list and count items matching a
    `PottoFeatureFilter`, which bundles paging, bbox, datetime, property filters and the CQL2 `filter`/`filter-lang`
    ([ADR-cql2]). Counting is separate so the total can be skipped when it is expensive;
  - `get_feature(feature_id, crs)`: fetch one item in the requested CRS, or `None`;
  - `get_schema()` and `get_queryables()`: JSON Schema for the collection's items and for its queryable properties;
  - `get_storage_crs()`, `get_spatial_extent()`, `get_temporal_extent()` and `get_additional_extents()`: let the data
    describe itself, so extents don't have to be maintained by hand in the collection description;
- Providers return potto schema objects (`Feature`, `CountedItems`, ...), never HTTP responses. Links, formats and
  HTML are added by the web layer ([ADR-http-agnostic]);
- Providers are read-only for now.

<!-- TODO: decide whether/when to add transactions (OGC API – Features Part 4: create/replace/update/delete items)
and whether that becomes an optional capability, as with managers. -->

### Consequences

- Good, because providers can use async drivers and avoid blocking the event loop;
- Good, because each method is small and typed, making providers easier to write and test;
- Good, because extents and schemas come from the data, reducing configuration drift;
- Bad, because every provider must implement all methods, including extents and queryables, even when the source
  cannot compute them cheaply;
- Bad, because pygeoapi providers can't be used directly and need an adapter (the `pygeoapi` bridge provider);
- Bad, because each provider has to interpret filters itself, including CQL2, which is significant work per provider.


[ADR-providers]: 0012-mediate-collection-item-data-via-pluggable-providers.md
[ADR-cql2]: 0015-cross-cutting-cql2-filtering.md
[ADR-http-agnostic]: 0003-keep-potto-core-agnostic-of-http.md
