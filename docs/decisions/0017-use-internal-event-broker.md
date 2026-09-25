---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Use Mosquitto with MQTT v5 and FastStream as the internal event broker

## Context and Problem Statement

potto has adopted an event-driven architecture ([ADR-events]): domain events such as `PROCESS_CREATED` or job
status changes trigger long-running work (process deployment and job execution by the job manager
([ADR-job-manager]), data ingestion, tile generation) in background workers, and are fanned out to external
subscribers through a separate public broker ([ADR-public-broker]).

Internally, potto needs a broker that distributes each unit of work to exactly one worker in a group, lets worker
groups scale horizontally, survives restarts, and is simple to run next to potto in development, CI and production.
It is only reachable from potto's own processes, not from external clients.

Which broker and client library should potto use for internal event exchange?

## Considered Options

- [Mosquitto] with MQTT v5 shared subscriptions, consumed through [FastStream]
- RabbitMQ (AMQP), consumed through FastStream
- Redis Streams, consumed through FastStream
- NATS / JetStream, consumed through FastStream
- [amqtt] (the same pure-Python broker used for the public side)
- A task queue (Celery, arq, Dramatiq) instead of a broker

## Decision Outcome

Chosen option: "Mosquitto with MQTT v5 shared subscriptions, consumed through FastStream", because MQTT v5 shared
subscriptions give load-balanced worker groups out of the box, Mosquitto is lightweight, mature and trivial to run
as a container, and using MQTT internally means the same protocol and topic conventions serve both the internal and
the public side of potto's event model.

The design:

- A Mosquitto broker runs as an internal-only service (not exposed outside the deployment's network);
- potto's API processes publish domain events after the corresponding state change has been committed;
- Workers are FastStream apps. Each kind of work is handled by a consumer group using MQTT v5 shared subscriptions
  (`$share/<group>/<topic>`), so each event is processed by one worker in the group, and groups are scaled by adding
  workers;
- Delivery is at-least-once (QoS 1) with persistent sessions, so consumers must be idempotent;
- Events are thin: identifiers, type, status and links. Workers load full resources through the managers;
- The fan-out consumer that republishes events to the public broker is just another shared-subscription group on the
  internal broker ([ADR-public-broker]);
- FastStream isolates potto's code from the broker, so switching to another broker it supports (RabbitMQ, NATS, ...)
  would mostly be a configuration change.

<!-- TODO: decide the internal topic naming scheme, retention/persistence settings, and how dead-lettering or
retries of failed work are handled (MQTT has no native dead-letter queue). -->

### Consequences

- Good, because shared subscriptions give horizontally scalable worker groups without extra machinery;
- Good, because Mosquitto is small, well-known and easy to run in docker compose for development and CI;
- Good, because one protocol (MQTT) is used for both internal and public events;
- Good, because FastStream provides typed, async consumers and keeps the broker swappable;
- Bad, because MQTT lacks features that work queues usually offer, such as dead-letter queues, delayed retries and
  message priorities, so these must be built in potto if needed;
- Bad, because it adds another service to deploy, monitor and secure, even for small deployments;
- Bad, because QoS 1 duplicates must be handled by idempotent consumers throughout.

Options not chosen, and why:

- RabbitMQ: more work-queue features (dead-lettering, TTLs), but heavier to run, and a different protocol from the
  public side;
- Redis Streams: convenient if Redis is already present, but persistence and consumer-group semantics are less
  suited to durable work distribution;
- NATS / JetStream: capable and fast, but one more technology for operators to learn, with no protocol overlap with
  the public side;
- amqtt: supports MQTT 3.1.1 only, so it has no shared subscriptions, which the worker groups depend on;
- A task queue: fits deferred work, but doesn't provide the event stream needed for public notifications, so a
  broker would still be needed.


[ADR-events]: 0016-adopt-event-driven-architecture.md
[ADR-public-broker]: 0018-public-mqtt-broker-and-authorization.md
[ADR-job-manager]: 0011-job-manager-protocol.md
[amqtt]: https://amqtt.readthedocs.io/en/latest/index.html
[FastStream]: https://faststream.ag2.ai/latest/
[Mosquitto]: https://mosquitto.org/
