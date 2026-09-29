---
icon: lucide/radio
---

# Pub/Sub

potto can notify external systems directly whenever its resources change. Notifications are delivered over [MQTT], a
lightweight publish/subscribe protocol with client libraries for pretty much every language and platform.

!!! info "OGC API - publish subscribe workflow draft standard"

    The OGC is preparing a specification for pub/sub workflows in the contenxt of OGC APIs. Its detail page is
    available at:

    https://ogcapi.ogc.org/pubsub/

In potto, there are two ways to receive events:

- Anonymously - connect to potto's MQTT broker without any credentials and subscribe to `public/...` topics.
- As an authenticated user - authenticate with potto, ask it for a pub/sub token and connect with it. In
  addition to the public topics, you can then also subscribe to your own `users/{user_id}/...` topics, which carry
  events about private resources that you are allowed to see

Either way, each event tells you what changed and links to it - you then fetch the resource through the API as
usual.

[MQTT]: https://mqtt.org/


!!! info "Events are notifications, not data"

    Events are deliberately thin: they say _what_ happened to _which_ resource, and link to it. They don't carry
    the resource itself. The API remains the source of truth, so always fetch the resource from the API to get its
    current state.

The design behind this is described in [ADR-0018](decisions/0018-public-mqtt-broker-and-authorization.md).

!!! tip "AsyncAPI document"

    potto describes its broker's topics and event payloads in an [AsyncAPI] 3.0 document, which is served by the API:

    - `/api/pubsub/docs` - interactive docs
    - `/api/pubsub/asyncapi.json` and `/api/pubsub/asyncapi.yaml` - the document itself, which can be used with
      AsyncAPI tooling, e.g. for generating clients

    The document describes what potto _sends_, so its operations are the ones that clients subscribe to.

    As advised by the draft OGC API - Pub/Sub standard, the API landing page links to the document with
    `rel: service-desc` and `type: application/asyncapi+json`, and to the interactive docs with `rel: service-doc`.

[AsyncAPI]: https://www.asyncapi.com/


## Topics

Topics are organized into two namespaces:

| Namespace              | Who can subscribe                                  | What gets published there                                |
|------------------------|----------------------------------------------------|----------------------------------------------------------|
| `public/`              | Everyone, including anonymous clients              | Events on public resources                               |
| `users/{user_id}/`     | Only the authenticated user whose id is `user_id`  | Events on private resources that the user is allowed to see |

Your `user_id` is potto's internal identifier for your account. It is returned by the token endpoint (see
[Connecting](#connecting)), together with your full topic prefix, so you don't need to work it out yourself.

### Process events

| Topic                                                   | Published when                          |
|---------------------------------------------------------|-----------------------------------------|
| `public/processes/{process_id}/created`                 | A public process is created             |
| `public/processes/{process_id}/updated`                 | A public process is modified            |
| `public/processes/{process_id}/deleted`                 | A public process is deleted             |
| `users/{user_id}/processes/{process_id}/created`        | A private process you can see is created  |
| `users/{user_id}/processes/{process_id}/updated`        | A private process you can see is modified |
| `users/{user_id}/processes/{process_id}/deleted`        | A private process you can see is deleted  |

For a private process, "you can see" means you are its owner, or it has been shared with you as an editor or as a
viewer.

!!! note "More events are on their way"

    Process events are the first kind of event supported by potto. Events for process deployments, collections
    and jobs are planned.

### Subscribing with wildcards

MQTT wildcards work as usual, as long as the subscription stays within your namespaces:

| Subscription                              | What you receive                                           |
|-------------------------------------------|------------------------------------------------------------|
| `users/{user_id}/#`                       | Everything about the private resources you can see         |
| `users/{user_id}/processes/+/deleted`     | Deletions of private processes you can see                 |
| `users/{user_id}/processes/my-process/#`  | Everything about the (private) process `my-process`        |
| `public/#`                                | Everything about public resources                          |
| `public/processes/+/created`              | New public processes                                       |

To follow everything you can see, subscribe to both `users/{user_id}/#` and `public/#`.

Subscriptions outside these namespaces - such as `#`, `users/+/#` or another user's namespace - are refused by the
broker, which answers them with the MQTT failure return code `0x80`.


## Event payload

Events are JSON documents, like this one:

```json
{
  "event_type": "updated",
  "process_identifier": "hillshade",
  "timestamp": "2026-09-28T13:04:51.192384Z",
  "links": [
    {
      "href": "https://potto.example.com/api/processes/hillshade",
      "rel": "self",
      "type": "application/json"
    }
  ]
}
```

| Field                | Description                                                                 |
|----------------------|-----------------------------------------------------------------------------|
| `event_type`         | What happened: `created`, `updated` or `deleted`                            |
| `process_identifier` | The identifier of the process                                               |
| `timestamp`          | When the change happened, in UTC                                            |
| `links`              | Links to the affected resource. Empty for `deleted` events, as there is nothing left to fetch |


## Connecting

potto's broker speaks MQTT 3.1.1, which is supported by virtually every MQTT client library. Ask your potto
administrator for the broker's address - it is also included in the token endpoint's response.

### Anonymous access

No potto account or token is needed to follow public resources. Connect without a username or password, then
subscribe to `public/#` or to any topic below it:

```shell
# for example, using mosquitto's `mosquitto_sub` CLI command
# to subscribe to all public events
mosquitto_sub -V mqttv311 -L "mqtts://mqtt.potto.example.com:8883/public/#" -v
```

Anonymous clients can only subscribe to `public/...` topics - subscriptions to anything else are refused.

### Authenticated access

Authenticate if you also want events about private resources that you are allowed to see.

1.  Authenticate with potto as you normally would. With local accounts, this means getting an access token from
    `POST /api/login`. With OIDC, use the access token issued by your identity provider.

2.  Request a pub/sub token:

    ```shell
    curl -X POST https://potto.example.com/api/pubsub/token \
        -H "Authorization: Bearer ${ACCESS_TOKEN}"
    ```

    Which would return something like this:

    ```json
    {
      "token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...",
      "token_type": "mqtt",
      "expires_at": "2026-09-28T13:34:51.192384Z",
      "username": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "topic_prefix": "users/7c9e6679-7425-40de-944b-e07fc1f90ae7/",
      "public_topic_prefix": "public/",
      "broker_url": "mqtts://mqtt.potto.example.com:8883"
    }
    ```

3.  Connect to the broker, sending the `token` as the MQTT password. The broker takes your identity from the token
    and ignores the MQTT username, but using the `username` from the response is a good choice.

4.  Subscribe to topics under your `topic_prefix` and/or under `public_topic_prefix`.

=== "mosquitto_sub"

    ```shell
    mosquitto_sub -V mqttv311 \
        -L "mqtts://${USERNAME}:${TOKEN}@mqtt.potto.example.com:8883/users/${USERNAME}/#" \
        -v
    ```

=== "Python (amqtt)"

    ```python
    import asyncio

    import httpx
    from amqtt.client import MQTTClient
    from amqtt.mqtt.constants import QOS_1


    async def main(access_token: str) -> None:
        async with httpx.AsyncClient(base_url="https://potto.example.com") as http_client:
            response = await http_client.post(
                "/api/pubsub/token",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            details = response.json()

        broker_address = details["broker_url"].partition("://")[2]
        client = MQTTClient()
        await client.connect(
            f"mqtts://{details['username']}:{details['token']}@{broker_address}"
        )
        await client.subscribe(
            [
                (f"{details['topic_prefix']}#", QOS_1),
                (f"{details['public_topic_prefix']}#", QOS_1),
            ]
        )
        while True:
            message = await client.deliver_message()
            print(message.topic, message.data.decode())
    ```


## Things to keep in mind

- Tokens expire: Pub/sub tokens are short-lived - their expiry is given by `expires_at`. When a token expires the broker
  disconnects you. Request a fresh token and reconnect, ideally shortly before `expires_at`. MQTT 3.1.1 has no
  way to refresh credentials on a live connection, so reconnecting is the only option;

- An invalid token is an error: If you send a password and it isn't a valid, unexpired token, the broker refuses
  the connection. It never quietly downgrades you to anonymous access;

- Clients can only sibscribe to events: potto is the only publisher of events. Messages published by clients are
  discarded;

- Events may arrive more than once: Events are delivered with QoS 1 ("at least once"), so the same event may
  occasionally be delivered twice. Make your handling idempotent, for example by keeping track
  of `process_identifier`, `event_type` and `timestamp`;

- Permission changes apply from then on: If a resource is shared with you, made public or made private, this affects
  the events published afterwards. Events that were already delivered are not taken back, and you don't get past
  events for resources that are newly shared with you;

- job-related events are only sent to the job submitter;


## Running the potto message broker

The broker is a separate potto process, started with:

```shell
potto run-broker
```

It opens two listeners:

- The public listener (port 1884 by default) is where clients connect. This is the one to expose
  to the outside world, usually behind a TLS-terminating proxy or load balancer;
- The internal listener (port 1885 by default) is where potto's internal codebase connects to publish
  events, authenticating with a shared secret. **Do not expose this listener to the public Internet** - keep it
  reachable only from within your deployment's private network.

### Configuration

The broker is configured through potto's usual [configuration](configuration.md) mechanism, with the
`POTTO__EXTERNAL_MQTT_BROKER__` prefix. Each setting is needed by some of potto's processes:

| Setting                          | Description                                                                                                  |
|----------------------------------|--------------------------------------------------------------------------------------------------------------|
| `INTERNAL_URL`                   | Address of the broker's **internal** listener, which the potto codebase uses in order to know where to publish to. The broker binds its internal listener on all interfaces, on this URL's port, which must be given explicitly. Default: `mqtt://localhost:1885` |
| `PUBLISHER_PASSWORD`             | Shared secret for publishing on the internal listener. Required by the worker and the broker                 |
| `PUBLIC_BIND`                    | Address and port for the public listener. Default: `0.0.0.0:1884`                                            |
| `TOKEN_SIGNING_KEY`              | PEM-encoded Ed25519 private key used for signing pub/sub tokens. Required by the API server                  |
| `TOKEN_PUBLIC_KEY`               | PEM-encoded Ed25519 public key matching `TOKEN_SIGNING_KEY`, used for verifying tokens. Required by the broker |
| `TOKEN_LIFETIME_MINUTES`         | Lifetime of pub/sub tokens, between 15 and 60 minutes. Default: `30`                                         |
| `EXPIRY_CHECK_INTERVAL_SECONDS`  | How often the broker disconnects clients with an expired token. Default: `10`                                |
| `PUBLIC_URL`                     | Broker address advertised to clients in the token endpoint's response, e.g. `mqtts://mqtt.potto.example.com:8883`. Required by the API server |

Each potto process refuses to start when a setting it requires is missing:

| Process                       | Required settings                        |
|-------------------------------|------------------------------------------|
| API server (`potto run-server`) | `PUBLIC_URL`, `TOKEN_SIGNING_KEY`        |
| Worker (`potto run-worker`)     | `PUBLISHER_PASSWORD`                     |
| Broker (`potto run-broker`)     | `PUBLISHER_PASSWORD`, `TOKEN_PUBLIC_KEY` |

The broker only ever needs the public key - give the private `TOKEN_SIGNING_KEY` to the API server alone.

??? info "Managing the broker signing keys"

    ### Generating a signing key

    Any tool that produces Ed25519 keys in PEM format will do. For example, with OpenSSL:

    ```shell
    # the private key, for TOKEN_SIGNING_KEY
    openssl genpkey -algorithm ed25519 -out potto-mqtt-signing-key.pem

    # the matching public key, for TOKEN_PUBLIC_KEY
    openssl pkey -in potto-mqtt-signing-key.pem -pubout
    ```

    Treat the private key and the publisher password like any other secret. Rather than setting them as environment
    variables, mount them as secret files - see [secrets](configuration.md) - e.g. as
    `/run/secrets/potto__external_mqtt_broker__token_signing_key` and
    `/run/secrets/potto__external_mqtt_broker__publisher_password`.

    ### Rotating keys

    To rotate the key, generate a new key pair, then give the new `TOKEN_SIGNING_KEY` to the API server and the new
    `TOKEN_PUBLIC_KEY` to the broker at the same time.

    Clients that are already connected stay connected, since tokens are only checked when a client connects. Tokens
    signed with the old key are refused from then on, so a client whose old token is refused on reconnect just
    requests a new one from the API, as it does whenever its token expires.
