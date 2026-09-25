---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Mediate access to collection item data via pluggable providers

## Context and Problem Statement

A collection's description is held by the collection manager ([ADR-collection-manager]), but its *items* (for
example, the features of a feature collection) can live anywhere: a PostGIS table, a GeoPackage or Shapefile, a
Parquet file queried with DuckDB, inline data in the collection's own configuration, or a pygeoapi provider. Two
collections served by the same potto instance will often use completely different data sources, and future data
types (coverages, tiles, records) will need their own kinds of sources.

How should potto access a collection's item data, independently of where the collection description is stored?

## Considered Options

- Per-collection pluggable providers, looked up by name in a registry and configured in the collection description
- Make the collection manager also serve item data
- Use pygeoapi's provider plugins directly for all item access

## Decision Outcome

Chosen option: "Per-collection pluggable providers, looked up by name in a registry", because it decouples *where a
collection is described* from *where its data lives*, lets each collection pick the best-suited source, and gives
potto a native, async interface instead of pygeoapi's synchronous one.

The design:

- Each collection carries a `providers` mapping from a `ProvidedDataType` (e.g. `feature`) to a `PottoProvider`
  (`schemas/base.py`): a `provider_name` plus a free-form `config` dict;
- Each data type has a provider protocol ([ADR-feature-provider] for features) and a registry built on the generic
  `providers/_registry.py::ProviderRegistry`, which maps provider names to factory functions;
- A factory takes `(collection, raw_config, potto_config)` and returns a provider instance, sync or async. The
  registry validates nothing about the config itself; each provider validates its own;
- Before calling the factory, `${ENV_VAR}` references in the provider config are interpolated, restricted by an
  `env_whitelist`, so secrets such as DB passwords need not be stored in the collection description;
- Provider instances are cached in a bounded cache keyed by collection and a hash of the provider config
  (`feature_provider_cache_size`, 0 disables it), so config changes produce a new instance;
- An unknown provider name is an error when the collection's data is accessed;
- The set of available providers is curated by potto ([ADR-builtin-providers]).

### Consequences

- Good, because each collection can use the most appropriate storage for its data;
- Good, because collection managers stay small and data-source agnostic, and read-only managers (e.g. from a TOML
  file) can still serve data from any source;
- Good, because providers can be natively async and potto-shaped, while pygeoapi providers remain usable through a
  bridge provider;
- Bad, because provider config is free-form, so a typo is only detected when the collection is first accessed, not
  when the collection is created;
- Bad, because potto cannot manage the lifecycle of the underlying data. Deleting a collection leaves its data
  source untouched;
- Bad, because caching provider instances means connections and file handles stay open until evicted.


[ADR-collection-manager]: 0009-collection-manager-protocol.md
[ADR-feature-provider]: 0013-feature-collection-item-provider-protocol.md
[ADR-builtin-providers]: 0014-provide-curated-builtin-item-data-providers.md
