---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Bake resource ownership and sharing into potto's core domain model

## Context and Problem Statement

Vanilla pygeoapi has no notion of users: every configured resource is world-readable, and access control, if any, is
bolted on in front of it by a reverse proxy or API gateway. That works for publishing open data, but not for a
multi-user server where people upload their own collections and processes, keep some of them private, and share them
with specific colleagues.

Access control that lives outside the application cannot filter listings ("which collections can *this* user
see?"), cannot drive the UI ("should the edit button be shown?"), and cannot decide who should receive a
notification about a private resource ([ADR-public-broker]).

Should ownership and sharing be part of potto's domain model, and if so, what should the model look like?

## Considered Options

- Ownership, visibility and sharing as first-class attributes of every top-level resource in the core model
- No ownership in potto; delegate all access control to an external gateway or proxy
- Generic ACL entries stored separately from resources, with no built-in concept of an owner
- Role-based access at the server level only (e.g. "editor" can edit every collection)

## Decision Outcome

Chosen option: "Ownership, visibility and sharing as first-class attributes of every top-level resource", because
it is the only option that lets potto filter listings, drive its UIs and scope notifications per user, while keeping
a model simple enough to explain in a few sentences (see `docs/resource-ownership.md`).

The design:

- Every top-level resource (collections, processes and, later, records) has an **owner**, which is a `PottoUser`
  (`schemas/collections.py::Collection.owner`, `schemas/processes.py::Process.owner`);
- Resources are **private by default** (`is_public = False`). A private resource is visible and actionable only by its
  owner, by admins and by users it has been shared with;
- An owner can **publish** a resource (`is_public = True`), making it world-readable, including for anonymous users;
- An owner can **share** a resource by granting another user one of two roles:
  - `viewer`: can see the resource, even if it is private;
  - `editor`: can modify the resource, including deleting it;
- Grants are part of the manager protocols (`grant_collection_access`/`revoke_collection_access`, and the process
  equivalents), and who holds a role on a resource can be looked up via
  `UserAccountProtocol.list_resource_editors`/`list_resource_viewers`;
- In the default implementation, grants are stored as dynamic user scopes following the
  `<resource-type>-<identifier>:<role>` convention (e.g. `collection-buildings:editor`), built by `PottoScope`
  helpers in `schemas/auth.py`;
- Only the owner or an admin may change a resource's owner;
- The *decision* about who may do what is always taken by the authorization backend ([ADR-authz]), which receives
  the resource (with its owner, visibility and grants) as input. The model provides the facts, the backend applies
  the policy.

### Consequences

- Good, because listings, detail pages, UIs and notifications can all be scoped per user from the same facts;
- Good, because the model is simple and familiar (it mirrors file-sharing services);
- Good, because it provides the input that alternative policy engines such as OPA need, without hardcoding the policy;
- Bad, because every manager implementation must store and return owner, visibility and grants, even read-only ones
  like the configuration file manager;
- Bad, because the two fixed roles (`viewer`, `editor`) may be too coarse for some deployments, e.g. "can edit but
  not delete";
- Bad, because encoding grants as user scopes ties sharing to the user account store and makes "who can see this
  resource?" a scan over users rather than a lookup on the resource;
- Bad, because there are no group or organization grants yet, only per-user ones.


[ADR-authz]: 0006-pluggable-authorization-with-local-and-opa.md
[ADR-public-broker]: 0018-public-mqtt-broker-and-authorization.md
