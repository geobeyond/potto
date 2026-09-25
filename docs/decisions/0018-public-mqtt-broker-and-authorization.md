---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Use amqtt with a custom token plugin as the public MQTT broker, with authorization enforced through audience-scoped topics

## Context and Problem Statement

Following the adoption of an event-driven architecture ([ADR-0016](0016-adopt-event-driven-architecture.md)), potto publishes domain events
(e.g. `collection_item_added`, job status changes) through a [FastStream] app. Internally, a [Mosquitto] broker
([ADR-internal-broker]) running MQTT v5 distributes work to worker groups using shared subscriptions. External clients also need to receive
event notifications, through a separate public broker.

Every resource in potto has an owner, and not all resources are public. Ownership is defined at the collection level
for collections and at the process level for processes, and job events belong to the user who submitted the job.
So not every subscriber to a topic such as `collections/{collection_id}/items/+` may receive every
event: authorization has to apply to each event, not just to each connection. potto's authentication layer supports
both OIDC and local accounts, so broker authentication must not depend on any single identity provider.

How should the public broker authenticate clients and make sure each event reaches only the users allowed to see it?

## Considered Options

- [amqtt] as public broker, with a custom Python auth/topic plugin, potto-issued MQTT tokens and audience-scoped topics
- Mosquitto as public broker, with [mosquitto-go-auth] delegating authn/authz to potto over HTTP
- Mosquitto as public broker, with a custom native plugin (C/Rust) delegating authn/authz to potto over HTTP
- Mosquitto as public broker, with the Dynamic Security plugin, potto-managed MQTT credentials and audience-scoped topics
- [EMQX] as public broker, using its built-in HTTP/JWT authn and authz
- amqtt for both the internal and the public broker

## Decision Outcome

Chosen option: "amqtt as public broker, with a custom Python auth/topic plugin, potto-issued MQTT tokens and
audience-scoped topics", because it gives the simplest auth model:

- no credential lifecycle to sync between potto and the broker;
- no per-message authorization callbacks on the broker's hot path;
- a broker-side plugin that is independent of how the user authenticated with potto;
- the internal Mosquitto broker stays unchanged, keeping MQTT v5 shared subscriptions for worker groups.

The design:

- Authorization moves into potto (audience-scoped topics) - A FastStream fan-out consumer on the internal broker
  (in a shared-subscription group) resolves each event's audience with potto's authz logic and republishes it to the
  public broker, once per recipient:

  - `public/...` for public resources;
  - `users/{user_id}/collections/{cid}/...` for the owners and editors of private collections;
  - `users/{user_id}/processes/{pid}/...` for process events;
  - `users/{submitter_id}/processes/{pid}/jobs/{jid}` for job events, which go to the submitter only.

  The broker only enforces namespaces.

- Authentication is by token exchange - An authenticated user, whether OIDC or local, calls `POST /pubsub/token`.
  potto returns a short-lived JWT: `iss` is `potto`, `aud` is `potto-mqtt`, `sub` is potto's internal user ID,
  lifetime is 15–60 minutes. It is signed with an asymmetric key and carries a `kid`. Clients send it as the
  MQTT password.

- Broker plugin - This is a custom amqtt auth plugin plus a topic plugin, shipped in the potto package and registered
  via entry points:

  - The auth plugin validates the token against potto's public key(s), loaded from configuration rather than fetched
    from the API at runtime. It sets the session username from `sub` and ignores the username the client sent.
  - A connection without a password is treated as anonymous; an invalid or expired token is rejected, never downgraded to anonymous.
  - The topic plugin allows SUBSCRIBE on `public/#` for everyone and on `users/{username}/#` for authenticated users.
    It denies PUBLISH for all external clients.
  - It enforces token expiry after connect (reject or disconnect at `exp`), since MQTT 3.1.1 has no re-authentication.

- Publishing - Done only by potto's FastStream app, through a listener bound to the internal network;
- Events are thin - IDs, type, status and links. Clients fetch full resources and job results through the API,
  which remains the authoritative enforcement point;
- User IDs used in topics - These must be stable, opaque and never contain `/`, `+` or `#`;
- Operations - A new potto CLI command (e.g. `potto broker serve-public`) runs the public broker as its own process
  or container, configured from potto's settings;
- Anonymous job notifications** are not offered. Anonymous users poll `/jobs/{jobId}` or use the OGC API – Processes
  callback URIs.

### Consequences

- Good, because authorization logic lives in one place (potto) and is reused as-is by the fan-out consumer;
- Good, because potto's authn modes (OIDC, local accounts, future ones) never change broker-side code;
- Good, because the broker holds only public keys and no user credentials or ownership state, so there is nothing
  to reconcile;
- Good, because no authorization call runs per message on the broker, so delivery doesn't depend on potto's
  availability once clients are connected;
- Good, because the plugin is Python in the same codebase, so it is easy to test and evolve;
- Bad, because there are two broker technologies (Mosquitto internal, amqtt public) to operate and understand;
- Bad, because amqtt supports MQTT 3.1.1 only, so public clients get no MQTT 5 features and token expiry has to be
  enforced by the plugin;
- Bad, because amqtt is a pure-Python asyncio broker, less mature and lower-throughput than Mosquitto. It must be
  load-tested at expected subscriber counts;
- Bad, because audience fan-out duplicates each event once per recipient. This is cheap for jobs (one recipient)
  but grows with the number of editors per collection;
- Bad, because visibility and membership changes apply to events published afterwards, not to events already delivered;
- Bad, because topics no longer mirror API paths one-to-one, so clients must learn their topic prefix
  (e.g. from the token response or links in API responses).

Options not chosen, and why:

- mosquitto-go-auth: archived by its maintainer in 2025, so it is unmaintained code in the security path;
- A custom native Mosquitto plugin: significant C/FFI work, and blocking HTTP calls from inside Mosquitto's
  single-threaded loop stall the whole broker;
- Mosquitto Dynamic Security: viable (with `%u` ACL patterns since Mosquitto 2.1), but it needs a credential-issuing
  endpoint, broker state synced and reconciled with potto's database, and one password per user shared across devices.
  It remains a possible fallback if amqtt fails load testing;
- EMQX: strong built-in auth, but it adds a third broker technology and has licensing to evaluate;
- amqtt for both brokers: rejected, because amqtt has no MQTT v5 shared subscriptions, which the internal worker groups depend on;


[amqtt]: https://amqtt.readthedocs.io/en/latest/index.html
[EMQX]: https://www.emqx.com/en
[FastStream]: https://faststream.ag2.ai/latest/
[Mosquitto]: https://mosquitto.org/
[mosquitto-go-auth]: https://github.com/iegomez/mosquitto-go-auth
[ADR-internal-broker]: 0017-use-internal-event-broker.md
