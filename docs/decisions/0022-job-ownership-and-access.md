---
status: proposed
date: 2026-09-30
decision-makers: Ricardo
---

# Give jobs an owner, and inherit their sharing from the parent process

## Context and Problem Statement

Processes are top-level resources. As such, they have an owner, are private by default, can be made public and can
be shared with other users as viewers or editors ([ADR-ownership]). Jobs, which are created by executing a process
([ADR-job-manager]), do not yet have an ownership and access model.

If jobs were not owned, they would be world-readable: anyone could list them and grab their results. This does not
fit in with the rest of potto's model, where private resources stay private. Moreover, most of the value of
controlling access to a job lies in controlling access to its results. If job results are accessible only through
their job, then job access control also covers results, and there is no need for a separate ownership and access
layer on results.

Who owns a job, what does owning a job allow, and can jobs be shared with other users or made public?

## Considered Options

- Jobs are owned and, by default, shared with the users that have access to the parent process;
- Jobs are owned and, by default, shared with nobody;
- Jobs are not owned, and are world-readable;
- Jobs and job results each have their own, separate ownership and sharing.

## Decision Outcome

Chosen option: "Jobs are owned and, by default, shared with the users that have access to the parent process",
because it keeps jobs private while letting the people who work on a process see its jobs and their results without
any extra sharing step. It reuses the vocabulary of [ADR-ownership] (owner, public, viewer, editor), and access to
results follows access to the job.

The design:

- Owning or being an editor of a job allows:
    - reading the job details;
    - reading the job results;
    - cancelling the job;
    - deleting the job;
    - deleting the job results;
- Being a viewer of a job allows reading the job details and the job results;
- Who may create a job depends on the parent process:
    - a private process can have jobs created by its owner, its editors and its viewers;
    - a public process can have jobs created by anyone, including anonymous users;
- Whoever creates a job becomes its owner. Anonymous users have no identity, so a job created anonymously on a public
  process is owned by the process owner;
- Jobs are private by default. The job owner may make a job public, at which point anonymous users can read the job
  details and its results. Being public is never the default, except for jobs created anonymously, which are always
  public, as otherwise their creator could not retrieve them;
- By default, a job is shared along with its parent process:
    - the process owner is a job editor;
    - the process editors are job editors;
    - the process viewers are job viewers;
- These inherited grants are derived from the parent process's current grants, not copied onto the job. Changing
  who a process is shared with also changes who can access its jobs;
- The job owner can further share the job with other users, as viewers or editors, on top of the inherited grants;
- Job results have no ownership of their own. Access to a job's results is always decided by access to the job;
- Job status notifications ([ADR-public-broker]) go to the owner, editors and viewers of private jobs only.
  Public jobs, including all jobs created anonymously, send no notifications. Their users poll `/jobs/{jobId}` or
  use OGC API - Processes callback URIs;
- As for other resources, the decision is taken by the authorization backend ([ADR-authz]). It gets new permission
  checks for jobs (e.g. `can_create_job`, `can_view_job`, `can_cancel_job`, `can_delete_job`), which receive both
  the job and its parent process, since the inherited grants come from the latter.

### Consequences

- Good, because jobs follow the same ownership and sharing model as top-level resources;
- Good, because collaborators on a private process can see its jobs and results without extra sharing steps;
- Good, because there is a single access control layer covering both jobs and their results;
- Good, because anonymous execution of public processes is supported, which may be useful for internal deployments;
- Good, because not sending notifications for public jobs keeps job events out of the public topic namespace;
- Bad, because jobs created anonymously are public, so any anonymous user can see other anonymous users' jobs and
  results;
- Bad, because the process owner owns every job created anonymously on their process, including its results and the
  storage they use, without having submitted them;
- Bad, because the viewers of a private process can create jobs, and therefore consume compute resources;
- Bad, because deciding access to a job needs its parent process too, which makes authorization checks and filtered
  job listings more expensive;
- Bad, because users of public jobs, including all anonymous users, get no push notifications;
- Bad, because the authorization backend protocol grows by a few more methods, to be implemented by both the local
  and the OPA backends.


[ADR-ownership]: 0004-bake-resource-ownership-and-sharing-into-core-model.md
[ADR-authz]: 0006-pluggable-authorization-with-local-and-opa.md
[ADR-job-manager]: 0011-job-manager-protocol.md
[ADR-public-broker]: 0018-public-mqtt-broker-and-authorization.md
