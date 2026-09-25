---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Adopt an event-driven architecture, internally for deferred processing and publicly for notifications


## Context and Problem Statement

Several of potto's operations are long-running and can't complete timely within an HTTP request/response cycle.
Examples include _OGC API – Processes_ job execution, data ingestion and tile generation. Running these in-band
within the API process ties up request workers, fails under load or on restart, and makes it hard to scale that
work independently of the API.

At the same time, OGC's API standards are moving beyond request/response. OGC API – Processes Part 1 already defines
asynchronous execution with job status and notification callbacks. OGC's newer work, such as the OGC API – Pub/Sub
effort (described with AsyncAPI) and the pub/sub bindings in OGC API – Connected Systems, points towards clients
subscribing to changes in resources rather than polling for them. If potto is to follow these standards as they
mature, it needs a way to push notifications about resource changes and job progress to external clients.

How should potto handle long-running work internally, and how should it expose resource and job changes to external clients?


## Considered Options

- An event-driven architecture on a message broker (MQTT via FastStream): events for internal deferred processing,
  and a public pub/sub interface for clients
- Synchronous processing within the request, with clients polling the API for changes
- In-process background tasks (e.g. FastAPI `BackgroundTasks` or an asyncio task pool), with clients polling
- A dedicated task queue or workflow orchestrator (e.g. Celery, Prefect) for long-running work, with polling and webhooks for clients


## Decision Outcome

Chosen option: "An event-driven architecture on a message broker (MQTT via FastStream)", because it meets both needs
with one model. Internally, long-running work is triggered by events and handled by scalable worker groups. Publicly,
the same domain events become the basis of the notification interface that OGC's pub/sub work is converging on.

The design:

- Domain events - potto emits domain events such as `PROCESS_CREATED` and job status changes after the corresponding
  state change is committed.
- Internal broker - Domain events are exchanged over an internal broker, recorded in [ADR-internal-broker].
- Asynchronous API responses - The API accepts long-running requests and answers immediately with a resource that
  can be tracked, such as `201` with `Location: /jobs/{jobId}` for OGC API – Processes. Clients can then poll, use
  the Part 1 callback URIs, or subscribe to events.
- Public broker - A separate public MQTT broker exposes event notifications to external clients. Its authentication,
  authorization and technology choice are recorded in [ADR-0018](0018-public-mqtt-broker-and-authorization.md).
- Thin events - Events carry identifiers, type, status and links. The API remains the source of truth for full
  resource representations.

### Consequences

- Good, because long-running operations no longer block API workers, and can be scaled, retried and restarted independently;
- Good, because a single event model serves both internal processing and public notifications:;
- Good, because it aligns potto with OGC's direction on asynchronous and pub/sub interfaces, with clean touch points
  for OGC API – Processes (async jobs), Connected Systems and Pub/Sub as those standards mature;
- Good, because MQTT is lightweight, widely supported by clients, and the protocol used in OGC's pub/sub bindings;
- Bad, because broker infrastructure has to be deployed, monitored and secured;
- Bad, because eventual consistency, duplicate delivery (QoS 1) and idempotent consumers become design concerns throughout the codebase;
- Bad, because debugging and tracing a flow of work across asynchronous components is harder than following a request;
- Bad, because a public event interface adds per-event authorization concerns for resources that aren't public (addressed in [ADR-0018]);
- Bad, because OGC's pub/sub standards are still evolving, so parts of the public event interface (topic layout,
  payload format) may need to change to conform later;


[ADR-0018]: 0018-public-mqtt-broker-and-authorization.md
[ADR-internal-broker]: 0017-use-internal-event-broker.md
