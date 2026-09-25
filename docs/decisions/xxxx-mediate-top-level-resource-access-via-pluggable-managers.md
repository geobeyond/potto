---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Mediate access to top-level resources via pluggable managers

## Context and Problem Statement

potto serves several kinds of top-level resources: its own server metadata, collections, processes, jobs and user
accounts. Early on, these were read and written directly through a single PostgreSQL database, hardcoded throughout
the codebase.

Deployments have different needs. A demo or small deployment may want a static configuration file, like pygeoapi,
with no database at all. A larger one wants a database with full read/write access. Others may want to load
collections from an external catalogue, or keep user accounts in a different store. potto should support these
without forking or patching the codebase, and the rest of potto (API, admin UI, CLI) should not care which one is in
use.

How should potto access its top-level resources so that the storage backend can be swapped per deployment?

## Considered Options

- One pluggable manager protocol per resource type, each configured independently with a factory and a settings dict
- A single monolithic storage backend interface covering all resource types
- A fixed PostgreSQL backend, with other sources imported into it
- Use pygeoapi's configuration file as the only source of resources

## Decision Outcome

Chosen option: "One pluggable manager protocol per resource type, each configured independently", because it keeps
each contract small and focused, lets one class implement several of them when that is convenient, and lets a
deployment mix backends per resource type.

The design:

- Each resource type has its own manager protocol:
  - server metadata: [ADR-server-metadata-manager]
  - collections: [ADR-collection-manager]
  - processes: [ADR-process-manager]
  - jobs (and job results): [ADR-job-manager]
  - user accounts: `managers/useraccounts.py::UserAccountProtocol`
- Protocols are structural ([ADR-protocols]). One class may implement several, like `PostgisManager` does;
- Each protocol module defines its protocol, a factory type alias
  (`Callable[[dict[str, Any], PottoSettings], XProtocol]`) and uses a frozen **capabilities** dataclass (e.g.
  `CollectionManagerCapabilities.supports_creation`). Reading is always supported; mutations are optional
  capabilities. A manager that lacks a capability raises `CapabilityNotSupported`;
- Every protocol shares a small set of members: `check_health()`, a `potto_cli_group` name and `get_cli_group()` to
  contribute CLI commands, and a `get_<x>_admin_view()` to contribute an admin UI view. This lets a manager bring its
  own tooling (e.g. the postgis manager's migration commands) without a central `potto db` command;
- Paginated listings take a single filter dataclass (`CollectionFilter`, `ProcessFilter`, `UserFilter`, ...) instead of
  ad hoc parameters;
- Managers always enforce authorization: every method takes the requesting user and checks the authorization
  backend ([ADR-authz]) before acting. Capabilities say what the backend *can* do, authorization says what *this
  user* may do;
- Managers exchange only `schemas.*` objects with the rest of potto, never their own storage types;
- Configuration: each resource type has a `<x>_manager` settings field with a `manager_factory`
  (`pydantic.ImportString`, a dotted path) and a free-form `settings_model` dict, validated by the factory itself.
  `PottoSettings.get_<x>_manager()` builds and caches managers lazily. Everything can be set with nested env vars,
  e.g. `POTTO__COLLECTION_MANAGER__MANAGER_FACTORY`;
- potto ships two managers: the PostGIS manager (reference implementation, full read/write) and the configuration
  file manager (read-only, TOML file, no database). See `docs/managers.md`;
- A shared contract test suite (`tests/test_manager_contract.py`) runs the same behavioural tests against every
  manager.

### Consequences

- Good, because deployments can choose, and mix, storage backends through configuration only;
- Good, because a database becomes an implementation detail of one manager, not a requirement of potto;
- Good, because capabilities let the API, UI and CLI adapt (e.g. hide "create" buttons) to read-only backends;
- Good, because the contract suite gives new managers a clear conformance target;
- Bad, because there is some configuration repetition: the all-postgis deployment sets the same DSN once per
  resource type;
- Bad, because cross-resource operations (e.g. deleting a user who owns collections) can span managers that don't
  share a transaction;
- Bad, because every manager must implement ownership, visibility and authorization checks, even trivial read-only
  ones.


[ADR-protocols]: xxxx-prefer-structural-subtyping-over-inheritance.md
[ADR-authz]: xxxx-pluggable-authorization-with-local-and-opa.md
[ADR-server-metadata-manager]: xxxx-server-metadata-manager-protocol.md
[ADR-collection-manager]: xxxx-collection-manager-protocol.md
[ADR-process-manager]: xxxx-process-manager-protocol.md
[ADR-job-manager]: xxxx-job-manager-protocol.md
