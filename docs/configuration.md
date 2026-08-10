# Configuration

potto uses [pydantic-settings] for its configuration. It is configured to be able to read its configuration from
the environment.

[pydantic-settings]: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/


##### bind_host: str = "127.0.0.1"
Hosts that are allowed to make requests to potto. You can set this to `"0.0.0.0"` in order to accept connections
from the world.

##### bind_port: int = 3001
Port on which the uvicorn web server started by potto when running `potto run-server`

##### debug: bool = False
##### database_dsn: PostgresDsn = "postgresql+psycopg://potto:pottopass@localhost/potto"
##### test_database_dsn: PostgresDsn = "postgresql+psycopg://potto:pottopass@localhost/potto_test"
##### public_url: str = "http://localhost:3001"
