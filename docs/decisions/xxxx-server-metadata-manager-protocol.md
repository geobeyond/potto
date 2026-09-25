---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define a server metadata manager protocol for potto's own metadata

## Context and Problem Statement

An OGC API server describes itself: title, description, keywords, contact point, license, data provider, terms of
service. potto uses this metadata in the landing page, in the web UI and in the OpenAPI document, which is built when
the app starts (`webapp/api/main.py::create_api_app_from_settings`).

In pygeoapi this metadata lives in the static configuration file. potto wants it to be editable at runtime from the
admin UI and CLI when the backend allows it, but still loadable from a static file in simple deployments
([ADR-managers]).

What contract should the component that holds potto's server metadata fulfil?

## Considered Options

- A dedicated `ServerMetadataProtocol` manager, with read access always supported and modification as an optional
  capability
- Keep server metadata in `PottoSettings` (environment variables / settings file)
- Store server metadata as part of another manager, e.g. the collection manager

## Decision Outcome

Chosen option: "A dedicated `ServerMetadataProtocol` manager", because server metadata is its own resource with its
own lifecycle and permissions, and a separate protocol lets it be backed by a database, a file or anything else
independently of the other resources.

The design:

- `managers/servermetadata.py::ServerMetadataProtocol` exposes:
  - `get_server_metadata() -> ServerMetadata`, always supported;
  - `update_server_metadata(update, user)`, gated by `ServerMetadataManagerCapabilities.supports_modification` and by
    the authorization backend's `can_edit_server_metadata`;
  - the members shared by all managers (`check_health`, CLI group, `get_server_metadata_admin_view`,
    `get_server_metadata_capabilities`);
- Server metadata is a **singleton**: there is exactly one per server. It has no owner and is always public;
- `ServerMetadataUpdate` is the canonical partial-update schema, only explicitly set fields are written. The CLI uses
  a flattened variant (`ServerMetadataFlattenedUpdate`) that is merged onto the existing metadata;
- When fields are unset (e.g. on a fresh install), consumers fall back to placeholder values, so potto can always
  start;
- The admin UI shows it as a single-instance view that skips the list page.

### Consequences

- Good, because administrators can change the server's description without redeploying, where the backend allows it;
- Good, because read-only deployments can serve metadata from a static file;
- Bad, because the OpenAPI document is built from the metadata at startup, so the metadata backend must be reachable
  for potto (and `potto export-openapi`) to start, and changes are not reflected in the OpenAPI document until a
  restart;
- Bad, because the singleton is enforced by convention in the manager, not by the protocol or the storage.

<!-- TODO: decide whether OGC API standard toggles should live here (see ADR on toggling OGC API standards) -->


[ADR-managers]: xxxx-mediate-top-level-resource-access-via-pluggable-managers.md
