---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define a process manager protocol for process descriptions

## Context and Problem Statement

OGC API – Processes exposes processes that clients can execute. Part 1 (Core) covers listing, describing and
executing processes; Part 2 (Deploy, Replace, Undeploy) lets clients add, change and remove processes at runtime,
submitting an *application package* that describes the process and its execution unit (e.g. an OCI image or a CWL
workflow).

In potto, processes are top-level resources with owners and visibility, just like collections ([ADR-ownership]),
and should be stored through a pluggable manager ([ADR-managers]). But a process involves two quite different
concerns: its *description* (identifier, title, version, inputs, outputs, execution unit, owner) and the machinery
needed to actually *run* it (container runtimes, CWL engines, clusters).

What contract should the component that holds processes fulfil, and where does running them fit?

## Considered Options

- A `ProcessManagerProtocol` that stores process descriptions only, mirroring the collection manager, with
  deployment and execution left to the job manager
- A single protocol that both stores and executes processes
- Processes defined in code only, as pygeoapi plugins

## Decision Outcome

Chosen option: "A `ProcessManagerProtocol` that stores process descriptions only", because storing a description
and running it have very different requirements and should be swappable independently: the same PostGIS-stored
process catalogue could be executed on a local container runtime, on Kubernetes or on a CWL engine.

The design:

- `managers/processes.py::ProcessManagerProtocol` mirrors the collection manager ([ADR-collection-manager]):
  - reads, always supported: `get_process(identifier, user)` and `paginated_list_processes(..., filter_)` with a
    `ProcessFilter`;
  - mutations, each gated by a `ProcessManagerCapabilities` flag: create, update and delete;
  - sharing, also capability-gated: grant/revoke `editor`/`viewer` access;
  - the members shared by all managers (`check_health`, CLI group, admin view, capabilities);
- A `Process` carries its `owner`, `is_public`, version, input and output descriptions, its **execution unit**
  (`ProcessExecutionUnitOci`, `ProcessExecutionUnitCwl` or `ProcessExecutionUnitOther`) and its **deployment status**
  (`queued`, `in-progress`, `deployed`, `failed`);
- The process manager **does not deploy, undeploy or execute processes**. OGC API – Processes Part 2 "deploy" at
  the API level means: store the description with the process manager, then ask the job manager to deploy it
  ([ADR-job-manager]), updating the stored deployment status as that work progresses;
- Both the PostGIS manager (read/write) and the configuration file manager (read-only) implement this protocol.

### Consequences

- Good, because process catalogues and execution backends can be chosen independently;
- Good, because the process manager stays simple and consistent with the collection manager;
- Good, because read-only process catalogues (from a configuration file) need no execution machinery just to be
  listed;
- Bad, because deploying a process spans two managers, so the deployment status stored with the process can be
  briefly out of step with the job manager's reality;
- Bad, because a process manager can accept a process whose execution unit type no job manager supports. This must be
  checked against the job manager's `supported_deployment_types` at deploy time.


[ADR-ownership]: xxxx-bake-resource-ownership-and-sharing-into-core-model.md
[ADR-managers]: xxxx-mediate-top-level-resource-access-via-pluggable-managers.md
[ADR-collection-manager]: xxxx-collection-manager-protocol.md
[ADR-job-manager]: xxxx-job-manager-protocol.md
