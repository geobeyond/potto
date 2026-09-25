---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define a collection manager protocol for collections

## Context and Problem Statement

Collections are the central resource of OGC API – Features (and of Coverages, Tiles, EDR, ...). potto needs to list,
search and describe collections, and, depending on the deployment, create, edit, delete and share them. Collections
have owners and may be private ([ADR-ownership]), and they may be stored in a database, a configuration file or an
external catalogue ([ADR-managers]).

A collection's *description* (identifier, title, extents, CRS, owner, visibility) is a different concern from its
*items* (the actual features), which may live in a completely different place, such as a GeoPackage file, a DuckDB
table or a remote service.

What contract should the component that holds collections fulfil?

## Considered Options

- A `CollectionManagerProtocol` for collection descriptions and sharing, with item data delegated to per-collection
  providers
- A single protocol covering both collection descriptions and item access
- Read-only collections defined in a configuration file, as in pygeoapi

## Decision Outcome

Chosen option: "A `CollectionManagerProtocol` for collection descriptions and sharing, with item data delegated to
providers", because it keeps the manager focused on metadata, ownership and access, and lets each collection choose
the most suitable data backend for its items ([ADR-providers]).

The design:

- `managers/collections.py::CollectionManagerProtocol` exposes:
  - reads, always supported: `get_collection(identifier, user)` and
    `paginated_list_collections(user, page, page_size, include_total, filter_)`;
  - mutations, each gated by a `CollectionManagerCapabilities` flag: `create_collection` (`supports_creation`),
    `update_collection` (`supports_modification`), `delete_collection` (`supports_deletion`);
  - sharing, also capability-gated: `grant_collection_access`/`revoke_collection_access` with an `editor`/`viewer`
    role (`supports_granting_access`/`supports_revoking_access`);
  - the members shared by all managers (`check_health`, CLI group, `get_collection_admin_view`,
    `get_collection_capabilities`);
- Listings only return collections the user may see. Filtering uses a `CollectionFilter` dataclass (identifier
  substring, collection type, spatial intersection), which is expected to grow into CQL2 support ([ADR-cql2]);
- Every returned `Collection` carries its `owner` and `is_public`, and its `providers` mapping, which tells potto
  which item data provider serves each data type (e.g. features) and with what configuration;
- Read and write schemas deliberately differ: `Collection` (read) uses `identifier`/`type_`, while
  `CollectionCreate`/`CollectionUpdate` (write) use `resource_identifier`/`collection_type`.

<!-- TODO: decide whether the read/write naming mismatch is intentional long-term or should be unified -->

### Consequences

- Good, because managers deal only with metadata and access, which is small and easy to store anywhere;
- Good, because read-only backends (e.g. the configuration file manager) are first-class, with capabilities telling
  UIs what to hide;
- Good, because one collection's item data can live in a completely different system from its description;
- Bad, because deleting or changing a collection's provider configuration does not clean up the underlying item
  data, which is outside the manager's control;
- Bad, because the differing field names between read and write schemas are an easy source of mistakes;
- Bad, because `Collection` does not yet expose `additional_extents`, although the write schemas do.


[ADR-ownership]: xxxx-bake-resource-ownership-and-sharing-into-core-model.md
[ADR-managers]: xxxx-mediate-top-level-resource-access-via-pluggable-managers.md
[ADR-providers]: xxxx-mediate-collection-item-data-via-pluggable-providers.md
[ADR-cql2]: xxxx-cross-cutting-cql2-filtering.md
