---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Define a job manager protocol, responsible for deploying, undeploying and executing processes

## Context and Problem Statement

The process manager stores process descriptions but deliberately does not run anything ([ADR-process-manager]).
Something still has to turn a process description into running work: pull an OCI image or register a CWL workflow
when a process is deployed, remove it when the process is undeployed, and, for each execution request, create an
OGC API – Processes *job*, run it, track its status and keep its results.

How this is done depends entirely on the execution environment: a local Docker/Podman daemon, a Kubernetes cluster,
a CWL engine such as Calrissian or Toil, an HPC scheduler, or a remote processing service. Each of these has its own
idea of what "deploying" a process means, and only the component that runs processes knows it.

Which component should own process deployment and job execution, and what contract should it fulfil?

## Considered Options

- A `JobManagerProtocol` that owns both process deployment/undeployment and job execution
- Deployment in the process manager, execution in the job manager
- A separate deployment manager, alongside the process manager and the job manager
- Delegate execution entirely to pygeoapi's process plugins and manager

## Decision Outcome

Chosen option: "A `JobManagerProtocol` that owns both process deployment/undeployment and job execution", because
the component that runs a process is the only one that knows what deploying it involves. Keeping deployment next to
execution means that swapping the execution backend (say, Docker for Kubernetes) is a single configuration change,
and the process manager stays a pure catalogue.

**It is the job manager's responsibility to deploy and undeploy processes.** The process manager only records the
description and its deployment status; the job manager does the actual work and reports the result.

The design:

- `managers/jobs.py::JobManagerProtocol` exposes:
  - `supported_deployment_types`: which execution unit types the manager can run (`"oci"`, `"cwl"` or custom
    strings matching `ProcessExecutionUnitOther.type_`). potto checks a process's execution unit against it before
    asking for a deployment;
  - `deploy_process(process) -> ProcessDeploymentStatus` and `undeploy_process(process) -> ProcessDeploymentStatus`:
    prepare or tear down whatever the execution environment needs to run the process (pull images, register
    workflows, create templates, ...). They raise `DeploymentFailedException` when this cannot be done;
  - `create_job(to_create, user) -> Job`: create a job for a deployed process. Creating a job implicitly schedules its
    execution;
  - `get_job(identifier, user)` and `paginated_list_jobs(user, ..., filter_)` with a `JobFilter`;
  - `delete_job(identifier, user)`, gated by `JobManagerCapabilities.supports_deletion`, raising
    `CapabilityNotSupported` otherwise;
  - the members shared by all managers (`check_health`, CLI group, `get_job_admin_view`, `get_job_capabilities`), and a
    `JobManagerFactoryProtocol` factory alias ([ADR-managers]);
- Deployment, undeployment and execution are potentially long-running. They are never run inside an HTTP request:
  the API records the intent (e.g. deployment status `queued`, or a new job), answers immediately, and the work is
  carried out by background workers triggered by events ([ADR-events], [ADR-internal-broker]). Workers update the
  process's deployment status through the process manager, and job status through the job manager;
- Jobs belong to the user who submitted them. Job status notifications go to the submitter only
  ([ADR-public-broker]);
- Job *results* live behind a separate `managers/jobresults.py::JobResultManagerProtocol` (`get_job_result`,
  `paginated_list_job_results`, `delete_job_result`), so results can be stored (e.g. in object storage) independently
  of where jobs run.

<!-- TODO: the job and job result managers are not yet wired into config.py (no settings fields or getters), no
built-in implementation exists yet, and most schemas in schemas/jobs.py (Job, JobStatus, JobCreate, JobResult) are
still stubs. -->
<!-- TODO: decide whether the job result manager deserves its own ADR. -->

### Consequences

- Good, because the execution backend can be swapped by configuration, bringing its own deployment logic with it;
- Good, because the process manager stays a simple, backend-neutral catalogue;
- Good, because `supported_deployment_types` makes incompatibilities between a process and the execution backend
  explicit and detectable at deploy time;
- Good, because long-running deployment and execution are kept out of API workers;
- Bad, because a deployment involves two managers (process status in the process manager, actual deployment in the
  job manager), which must be kept consistent without a shared transaction;
- Bad, because a deployment exists only in the job manager's environment. Switching job managers means redeploying
  every process;
- Bad, because the protocol mixes two responsibilities (deployment and execution), so implementations are larger than
  those of the other managers.


[ADR-process-manager]: xxxx-process-manager-protocol.md
[ADR-managers]: xxxx-mediate-top-level-resource-access-via-pluggable-managers.md
[ADR-events]: xxxx-adopt-event-driven-architecture.md
[ADR-internal-broker]: xxxx-use-internal-event-broker.md
[ADR-public-broker]: xxxx-public-mqtt-broker-and-authorization.md
