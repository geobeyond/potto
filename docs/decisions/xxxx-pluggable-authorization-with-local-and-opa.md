---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Use pluggable authorization, with built-in backends for local authorization and OPA

## Context and Problem Statement

With resource ownership and sharing in the core model ([ADR-ownership]), potto has to decide on every operation
whether the requesting user may perform it: view a private collection, edit a process, assign the admin scope,
create a user, and so on. A sensible default policy covers most deployments, but organizations often have their own
rules ("members of group X may edit all collections tagged Y", "no public resources on this server") and may already
manage policies centrally with a policy engine.

These checks happen in the API, the admin UI, the CLI and, later, in the event fan-out that decides who receives
which notification ([ADR-public-broker]). They must all apply the same rules.

How should potto make authorization decisions, and how can deployments customize them?

## Considered Options

- A pluggable authorization backend protocol, with a built-in local (scope-based) backend and an Open Policy Agent
  (OPA) backend
- Hardcoded authorization checks spread through the routers and views
- A single built-in policy with configuration flags
- OPA only

## Decision Outcome

Chosen option: "A pluggable authorization backend protocol, with local and OPA backends", because it gives every
deployment a working default, lets policy-heavy deployments move their rules into a dedicated policy engine, and
keeps every check behind one interface that all entry points share.

The design:

- `authz/protocols.py::AuthorizationBackendProtocol` defines one async method per permission, such as
  `can_view_collection`, `can_edit_collection`, `get_accessible_collection_identifiers`, `can_create_process`,
  `can_assign_admin_scope` and `can_edit_server_metadata`. Each receives the requesting `PottoUser | None` (`None`
  means anonymous) and the relevant resource;
- **Local backend** (`authz/backend.py::LocalAuthorizationBackend`): implements the default policy from
  [ADR-ownership] using ownership, `is_public` and user scopes. `PottoScope.ADMIN` grants everything;
- **OPA backend** (`authz/opa.py::OPAAuthorizationBackend`): each check is a query to OPA's data API
  (`POST {opa.url}/v1/data/{opa.policy_path}/{rule}`) with the user and resource as input. Policies are Rego files
  managed outside potto (see `docker/opa/policies/` for the reference policy). OPA deployments do not support
  creating users in potto (`can_create_user` always returns `False`), since users come from the identity provider;
- The backend is selected by configuration: setting `settings.opa` enables OPA, otherwise the local backend is used;
- Checks are performed inside the manager operations (e.g. `managers/postgis/operations/`), not in the web layer, so
  the API, admin UI, CLI and workers can't bypass them. The CLI uses an admin-scoped system user rather than a
  bypass flag;
- Adding a permission means adding a method to the protocol, implementing it in both backends, adding a
  `PottoCannotXxxException` and checking it in the relevant operation.

<!-- TODO: backend selection is currently a hardcoded if/else on settings.opa (config.py::get_authorization_backend).
Decide whether to make it pluggable via an ImportString factory, like the resource managers. -->

### Consequences

- Good, because all entry points share one authorization interface and one policy;
- Good, because organizations can manage potto's policies alongside their other services' policies in OPA;
- Good, because authentication and authorization can be combined freely (local+local, OIDC+OPA, ...);
- Bad, because the protocol grows by one method per permission, and every backend must implement each one;
- Bad, because the OPA backend adds a network round-trip per check, which matters for listings and event fan-out.
  Caching or batching may be needed;
- Bad, because potto's Rego reference policy must be kept in step with the local backend's behaviour by hand.


[ADR-ownership]: xxxx-bake-resource-ownership-and-sharing-into-core-model.md
[ADR-public-broker]: xxxx-public-mqtt-broker-and-authorization.md
