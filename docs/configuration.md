# Configuration

potto uses [pydantic-settings] for its configuration. It is configured to be able to read its configuration from
the environment.

Settings can also be read from files in `/run/secrets`, which is where docker and kubernetes mount secrets. Each
file holds the value of one setting and is named like the setting's environment variable - for example, a file
named `/run/secrets/potto__external_mqtt_broker__token_signing_key` sets
`POTTO__EXTERNAL_MQTT_BROKER__TOKEN_SIGNING_KEY`. Use this for sensitive settings such as keys and passwords, so
that they do not show up in the process environment. Environment variables take precedence over secret files.

[pydantic-settings]: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/


##### bind_host: str = "127.0.0.1"
Hosts that are allowed to make requests to potto. You can set this to `"0.0.0.0"` in order to accept connections
from the world.

##### bind_port: int = 3001
Port on which the uvicorn web server started by potto when running `potto run-server`

##### debug: bool = False
##### public_url: str = "http://localhost:3001"

##### external_mqtt_broker
Settings for potto's public MQTT broker, which delivers event notifications to external clients. These are set
with environment variables named `POTTO__EXTERNAL_MQTT_BROKER__<SETTING>`, _e.g._
`POTTO__EXTERNAL_MQTT_BROKER__TOKEN_SIGNING_KEY`. See [Pub/Sub](pubsub.md#configuration) for the full list.
