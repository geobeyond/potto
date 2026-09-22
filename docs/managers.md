---
icon: lucide/plug
---

## Resource managers

potto resources are handled by _resource managers_. These are pluggable entities, which respect a
known protocol, and which are used by potto to provide access to the underlying resources.

!!! note

    While managers do mediate potto's access to underlying resources, note that they always enforce
    the access controls defined in the potto authorization backend.

    In other words, even if the manager capabilities report being able to create a new resource, this operation
    is always further gated by whether the requesting user is allowed to create the resource or not.

In addition to their own logic, managers can also:

- hook into the potto CLI and provide custom commands
- hook into the potto admin UI and provide custom views


### Server metadata manager

The server metadata manager handles potto's own metadata. It defines as its capabilities:

- Read access to the server metadata
- Optionally, mutating the server metadata


### User account manager

The user account manager handles potto's user accounts. It's capabillities are:

- Read access to potto users
- Optionally, mutating potto's user set and also modifying a user's properties
-

### Collection manager

The collection manager deals with collections. It implements the
``potto.collectionmanager.CollectionManagerProtocol``, which defines a set of capabilities:

- Read access to collections. This comprises listing, searching and filtering and getting details about existing
  collections. This is always implicitly enabled and represents the core responsibility of the manager.

- Optionally, mutating the set of collections known to potto. This comprises creating new collections, deleting
  and modifying existing collections.

- Optionally, managing users' access controls over private collections. This comprises granting and revoking
  access


### Process manager

The process manager deals with processes. It implements the
``potto.managers.processes.ProcessManagerProtocol``, which defines a set of capabilities:

- Read access to processes. This comprises listing, searching and filtering and getting details about existing
  processes. This is always implicitly enabled and represents the core responsibility of the manager.

- Optionally, mutating the set of processes known to potto. This comprises creating new processes, deleting
  and modifying existing processes.

- Optionally, managing users' access controls over private processes. This comprises granting and revoking
  access


## Built-in resource managers

potto comes with two built-in resource managers:

- Postgis manager - backed by a PostGIS DB
- configuration file manager - backed by a TOML configuration file


### Postgis manager

This is the reference implementation of the potto architecture. It is backed by a PostGIS DB and implements support
for all resource manager protocols.


#### Capabilities

The Postgis manager implements all resource protocols and provides read and write access to them.

| Resource type | Capability | Supported |
| ------------- | ---------- | --------- |
| Collection | read existing collections | :green_square: Yes |
| Collection | create new collections | :green_square: Yes |
| Collection | update existing collections | :green_square: Yes |
| Collection | delete existing collections | :green_square: Yes |
| Collection | grant access to private collection | :green_square: Yes |
| Collection | revoke access to private collection | :green_square: Yes |
| Process | read existing processes | :green_square: Yes |
| Process | create new processes | :green_square: Yes |
| Process | update existing processes | :green_square: Yes |
| Process | delete existing processes | :green_square: Yes |
| Process | grant access to private process | :green_square: Yes |
| Process | revoke access to private process | :green_square: Yes |
| Server metadata | read server metadata | :green_square: Yes |
| Server metadata | update server metadata | :green_square: Yes |
| User account | read existing users | :green_square: Yes |
| User account | create new users | :green_square: Yes |
| User account | update existing users | :green_square: Yes |
| User account | delete existing users | :green_square: Yes |


#### Set up

In order to enable the postgis manager, set the following configuration keys:

-  `collection_manager.manager_factory`: `potto.manager.postgis.manager:get_postgis_manager`
-  `collection_manager.settings_model`: this is a dictionary with the following keys:

    -  `database_dsn` - The sqlalchemy connection string
    -  `test_database_dsn` - The sqlalchemy connection string for connecting to a test database - This is only needed if you are a potto developer

-  `process_manager.manager_factory`: `potto.manager.postgis.manager:get_postgis_manager`
-  `process_manager.settings_model`: The same as the `collection_manager.settings_model`
-  `server_metadata_manager.manager_factory`: `potto.manager.postgis.manager:get_postgis_manager`
-  `server_metadata_manager.settings_model`: The same as the `collection_manager.settings_model`
-  `user_account_manager.manager_factory`: `potto.manager.postgis.manager:get_postgis_manager`
-  `user_account_manager.settings_model`: The same as the `collection_manager.settings_model`


Note that these can be set as environment variables, _e.g._:

```shell
POTTO__COLLECTION_MANAGER__MANAGER_FACTORY="potto.managers.postgis.manager:get_postgis_manager"
POTTO__COLLECTION_MANAGER__SETTINGS_MODEL__DATABASE_DSN="postgresql+psycopg://<user>:<password>@<host>:<port>/<db>"

POTTO__PROCESS_MANAGER__MANAGER_FACTORY="potto.managers.postgis.manager:get_postgis_manager"
POTTO__PROCESS_MANAGER__SETTINGS_MODEL__DATABASE_DSN="postgresql+psycopg://<user>:<password>@<host>:<port>/<db>"

POTTO__SERVER_METADATA_MANAGER__MANAGER_FACTORY="potto.managers.postgis.manager:get_postgis_manager"
POTTO__SERVER_METADATA_MANAGER__SETTINGS_MODEL__DATABASE_DSN="postgresql+psycopg://<user>:<password>@<host>:<port>/<db>"

POTTO__USER_ACCOUNT_MANAGER__MANAGER_FACTORY="potto.managers.postgis.manager:get_postgis_manager"
POTTO__USER_ACCOUNT_MANAGER__SETTINGS_MODEL__DATABASE_DSN="postgresql+psycopg://<user>:<password>@<host>:<port>/<db>"
```

??? detail "Repetitive settings?"

    The above settings keys seem repetitive - this is because the Postgis manager happens to implement the
    protocols for managing collections, server metadata and user accounts and these are independent entities, which
    therefore have their own configuration.

    This means that is also possible to use the Postgis manager just some of the reosurces and use a
    different manager for others. For example: you could use the Postgis manager for collections and user accounts
    and the configuration file manager (introduced below) for server metadata.


#### Potto Admin

The Postgis manager registers views in the potto admin area for

- collections
- processes
- server metadata
- user accounts

The admin can be used to manage the underlying resources, including modifying their respective properties.


#### CLI commands

The Postgis manager provides some additional potto CLI commands that are mostly useful for the potto developers. Check
them out with:

```shell
potto postgis-manager --help
```


### Configuration file manager

This is a read-only manager. It loads a static TOML file once at startup and serves everything
from memory. It does not depend on a database. It is a good fit for small, read-only, or demo deployments
that don't require frequent updates and don't mind a bit of downtime while the configuration file is updated.

!!! tip "pygeoapi alternative"

    The configuration file manager is a good alternative if you have used pygeoapi in the past, as it caters for the
    same use case. A lean static configuration file.


#### Configuration file schema

The configuration file is a [TOML] file with the following schema:

[TOML]: https://toml.io/en/

An array of `user_account` tables, where each `user_account` has the following properties:

| name | type | description | optional |
| ---- | ---- | ----------- | -------- |
| `id` | `str` | Identifier of the user | no |
| `username` | `str` | Username | no |
| `is_active` | `bool` | Whether the user is active | no |
| `scopes` | `array[Literal["admin"]]` | A list of scopes that the user has | no |
| `hashed_password` | `str` | The user's bcrypt hashed password | yes |


An array of `collection` tables, where each `collection` has the following properties:

| name | type | description | optional |
| ---- | ---- | ----------- | -------- |
| `identifier` | `str` | The public identifier of the collection | No |
| `type_` | `Literal[feature]` | The collection type | No |
| `owner_id` | `str` | `id` of the user who owns the collection | No |
| `is_public` | `bool` | Whether the collection is public | No |
| `title` | `str` | A title for the collection | No |
| `crs` | `list[str]` | A list of Coordinate Reference Systems for the collection | No |
| `created_at` | `datetime` | Creation date of the collection **NOTE**: This must be a TOML offset datetime | No |
| `updated_at` | `datetime` | Update date of the collection **NOTE**: This must be a TOML offset datetime | No |


An array of `process` tables, where each `process` has the following properties:

| name | type | description | optional |
| ---- | ---- | ----------- | -------- |
| `identifier` | `str` | The public identifier of the process | No |
| `owner_id` | `str` | `id` of the user who owns the process | No |
| `is_public` | `bool` | Whether the process is public | No |
| `title` | `str` | A title for the process | No |
| `version` | `str` | The process version | No |
| `created_at` | `datetime` | Creation date of the process **NOTE**: This must be a TOML offset datetime | No |
| `updated_at` | `datetime` | Update date of the process **NOTE**: This must be a TOML offset datetime | No |
| `inputs` | `array[table]` | The process' input descriptions | Yes |
| `outputs` | `array[table]` | The process' output descriptions | Yes |
| `execution_unit` | `table` | The process' execution unit (an OCI image, a CWL definition, or another custom type - picked by its `type_` field) | Yes |
| `deployment_status` | `table` | The process' deployment status. Defaults to `{ value = "failed" }` when omitted | Yes |


A `server_metadata` table with the following properties:

| name | type | description | optional |
| ---- | ---- | ----------- | -------- |
| `title` | `str` | The title of the potto server | No |



For example:

```toml
[[user_account]]
id = "u1"
username = "alice"
is_active = true
scopes = ["admin"]
hashed_password = "$2b$12$..."   # optional - omit for OIDC-only users

[[collection]]
identifier = "buildings"
type_ = "feature"           # a potto.constants.CollectionType value
owner_id = "u1"              # resolved against [[user_account]] entries
is_public = true
title = "Buildings"
crs = ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]
created_at = 2024-01-01T00:00:00Z
updated_at = 2024-01-01T00:00:00Z

[[process]]
identifier = "buffer"
owner_id = "u1"              # resolved against [[user_account]] entries
is_public = true
title = "Buffer"
version = "1.0.0"
created_at = 2024-01-01T00:00:00Z
updated_at = 2024-01-01T00:00:00Z

[process.execution_unit]
type_ = "other"
definition = { echo = "hello" }

[server_metadata]
title = "My potto server"
```

#### Capabilities

The configuration file manager implements all resource protocols but only provides read access to them.

| Resource type | Capability | Supported |
| ------------- | ---------- | --------- |
| Collection | read existing collections | :green_square: Yes |
| Collection | create new collections | :red_square: No |
| Collection | update existing collections | :red_square: No |
| Collection | delete existing collections | :red_square: No |
| Collection | grant access to private collection | :red_square: No |
| Collection | revoke access to private collection | :red_square: No |
| Process | read existing processes | :green_square: Yes |
| Process | create new processes | :red_square: No |
| Process | update existing processes | :red_square: No |
| Process | delete existing processes | :red_square: No |
| Process | grant access to private process | :red_square: No |
| Process | revoke access to private process | :red_square: No |
| Server metadata | read server metadata | :green_square: Yes |
| Server metadata | update server metadata | :red_square: No |
| User account | read existing users | :green_square: Yes |
| User account | create new users | :red_square: No |
| User account | update existing users | :red_square: No |
| User account | delete existing users | :red_square: No |


#### Set up

In order to enable the configuration file manager, set the following configuration keys:

-  `collection_manager.manager_factory`: `potto.managers.configurationfile.manager:get_configuration_file_manager`
-  `collection_manager.settings_model`: this is a dictionary with the following keys:

    -  `config_file` - Path to the TOML configuration file

-  `process_manager.manager_factory`: `potto.managers.configurationfile.manager:get_configuration_file_manager`
-  `process_manager.settings_model`: The same as the `collection_manager.settings_model`
-  `server_metadata_manager.manager_factory`: `potto.managers.configurationfile.manager:get_configuration_file_manager`
-  `server_metadata_manager.settings_model`: The same as the `collection_manager.settings_model`
-  `user_account_manager.manager_factory`: `potto.managers.configurationfile.manager:get_configuration_file_manager`
-  `user_account_manager.settings_model`: The same as the `collection_manager.settings_model`


Note that these can be set as environment variables, _e.g._:

```shell
POTTO__COLLECTION_MANAGER__MANAGER_FACTORY="potto.managers.configurationfile.manager:get_configuration_file_manager"
POTTO__COLLECTION_MANAGER__SETTINGS_MODEL__CONFIG_FILE="/etc/potto/my-config.toml"

POTTO__PROCESS_MANAGER__MANAGER_FACTORY="potto.managers.configurationfile.manager:get_configuration_file_manager"
POTTO__PROCESS_MANAGER__SETTINGS_MODEL__CONFIG_FILE="/etc/potto/my-config.toml"

POTTO__SERVER_METADATA_MANAGER__MANAGER_FACTORY="potto.managers.configurationfile.manager:get_configuration_file_manager"
POTTO__SERVER_METADATA_MANAGER__SETTINGS_MODEL__CONFIG_FILE="/etc/potto/my-config.toml"

POTTO__USER_ACCOUNT_MANAGER__MANAGER_FACTORY="potto.managers.configurationfile.manager:get_configuration_file_manager"
POTTO__USER_ACCOUNT_MANAGER__SETTINGS_MODEL__CONFIG_FILE="/etc/potto/my-config.toml"
```

??? detail "Repetitive settings?"

    The above settings keys seem repetitive - this is because the configuration file manager happens to implement the
    protocols for managing collections, server metadata and user accounts and these are independent entities, which
    therefore have their own configuration.

    This means that is also possible to use the configuration file manager just some of the reosurces and use a
    different manager for others. For example: you could use the Postgis manager (introduced above) for collections
    and user accounts and the configuration file manager for server metadata.

#### Potto admin

The configuration file manager registers views in the potto admin area for

- collections
- processes
- server metadata
- user accounts

The admin can be used to view the underlying resources but does not allow modifying them, since this is not supported
by the manager.


#### CLI commands

The configuration file manager does not provide any CLI commands.


## Implementing custom managers

1. Implement whichever protocol(s) it should back - one class may implement all of them.
2. Write a factory function that implements the respective factory protocol, which basically is just a function that takes two arguments:
       - `raw_config: dict` - whatever specific configuration the manager needs
       - `settings: PottoSettings` - the main potto settings

   This factory must return an instance of the manager

3. Point the relevant `manager_factory` setting at it.
4. Validate it against `tests/test_manager_contract.py`'s parametrized contract
   suite - add your manager as a new backend fixture there to confirm it conforms to
   the same protocol-level behavior as the existing managers.
