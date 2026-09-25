---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define extension points as `typing.Protocol`s and prefer structural subtyping over inheritance

## Context and Problem Statement

potto is built around extension points: resource managers ([ADR-managers]), item data providers ([ADR-providers]),
authorization backends ([ADR-authz]) and web helpers such as URL resolvers. Third parties must be able to implement
these without depending on potto internals, and a single class may reasonably implement several of them at once. For
example, `PostgisManager` backs collections, processes, server metadata and user accounts from one database.

Classic nominal subtyping (abstract base classes that implementations must inherit from) couples implementations to
potto's class hierarchy, invites shared mutable state in base classes, and makes multi-role classes awkward (multiple
inheritance, diamond problems, method name clashes).

How should potto define the contracts that its pluggable components must satisfy?

## Considered Options

- Structural subtyping with `typing.Protocol`, implementations are plain classes
- Nominal subtyping with `abc.ABC` base classes and `@abstractmethod`
- Concrete base classes with default behaviour that implementations override
- Duck typing with no formal contract, only documentation

## Decision Outcome

Chosen option: "Structural subtyping with `typing.Protocol`", because it lets potto state a precise, type-checkable
contract while leaving implementations completely free: they don't import or inherit from anything in potto just to
be accepted.

The design:

- Every extension point is a `typing.Protocol`:
  - `managers/{collections,processes,jobs,jobresults,servermetadata,useraccounts}.py`
  - `authz/protocols.py::AuthorizationBackendProtocol`
  - `providers/features/protocol.py::FeatureProviderProtocol`
  - `pygeoapi_providers/protocols.py::PygeoapiReadOnlyFeatureProviderProtocol`
  - `webapp/protocols.py::UrlResolver`
- Implementations are plain classes that match the protocol by shape. `PostgisManager`, `ConfigurationFileManager`,
  `LocalAuthorizationBackend` and `OPAAuthorizationBackend` do not subclass their protocols;
- Factories are expressed as `Callable` type aliases (e.g. `CollectionManagerFactoryProtocol`), so any function with
  the right signature works;
- `@runtime_checkable` is used only where potto actually needs to check an object at runtime, which today is only
  `FeatureProviderProtocol`;
- Because one class may implement several protocols, methods whose return type differs per protocol get
  entity-qualified names (`get_collection_capabilities`, `get_user_account_admin_view`, ...), while methods whose
  meaning is identical across protocols share a name (`check_health`, `get_cli_group`);
- Conformance is verified by the static type checker (`ty`) and by behavioural contract tests
  (`tests/test_manager_contract.py`), not by the class hierarchy.

### Consequences

- Good, because third-party implementations need no potto base class and cannot accidentally depend on base-class
  internals;
- Good, because one class can cleanly implement several protocols, as `PostgisManager` does;
- Good, because protocols document the contract in one place and are checked statically;
- Good, because test doubles are trivial to write, any object with the right methods will do;
- Bad, because there is no place to put shared default behaviour. Common logic must live in helper functions or be
  duplicated across implementations;
- Bad, because a non-conforming implementation is only caught by the type checker or at call time, not at class
  definition time (unless the protocol is `runtime_checkable`, which only checks method presence, not signatures);
- Bad, because the method-naming convention for multi-protocol classes must be followed carefully to avoid clashes.


[ADR-managers]: xxxx-mediate-top-level-resource-access-via-pluggable-managers.md
[ADR-providers]: xxxx-mediate-collection-item-data-via-pluggable-providers.md
[ADR-authz]: xxxx-pluggable-authorization-with-local-and-opa.md
