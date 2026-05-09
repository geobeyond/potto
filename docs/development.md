---
icon: lucide/hammer
---

# Development

## Quickstart

```shell
# start the docker compose stack
docker compose -f docker/compose.dev.yaml up -d --force-recreate

# set some env variables
export PYGEOAPI_ROOT="wherever-you-cloned-pygeoapi-repo"
POTTO__DATABASE_DSN="postgresql+psycopg://potto:pottopass@localhost:55432/potto"
export POTTO__DEBUG=true
export POTTO__PYGEOAPI_CONFIG_FILE=pygeoapi-config-example.yml
export POTTO__RELOAD_DIRS=$(pwd -P)
export POTTO__UVICORN_LOG_CONFIG_FILE=uvicorn-log-config-example.yml

# start the server
uv run potto run-server
```



## Contribution guidelines

Read the contribution guidelines, to be added...


## Setup

Contributing to potto requires a couple of pre-requisites to be met:

You should be running a linux distribution. Development might also be possible on other OS, but you'll be mostly
on your own with regard to how to set up your working environment

Additionally, the following tools need to be installed on your machine:

-  [git]
-  [pre-commit]
-  [uv]

Please refer to each tool's own documentation for how to get it installed

Finally, a [PostgreSQL] database with [PostGIS] installed. You can either use the potto-provided [docker compose]
file, which is suitable for development and includes a `db` service or install PostgreSQL and PostGIS in
whatever way you prefer and then create a database to be used for development.

[docker compose]: https://docs.docker.com/compose/
[git]: https://git-scm.com/
[PostgreSQL]: https://www.postgresql.org/
[PostGIS]: https://postgis.net/
[pre-commit]: https://pre-commit.com/
[uv]: https://docs.astral.sh/uv/


## Workflow

If you are not a core committer to potto, be sure to always open an issue that describes the problem,
feature or changes you'd like to materialize. This will provide visibility and give the potto devs
a chance to offer some feedback. If you don't do this, there is a risk that your work will be refused.

!!! warning

    Just in case you skipped the previous paragraph - **the potto team does not accept PRs without
    a corresponding issue**.

potto's code is developed by following the [forking workflow] collaboration strategy. In short:

1. Fork potto's repo
2. Clone your fork locally
3. Create a new branch
4. Make changes to the code
5. Open a Pull Request (PR) to get the changes integrated into the main potto repository
6. Follow the PR review process, responding to any comments or change requests
7. Rejoice when your PR is merged :smile: :tada:

[forking workflow]: https://www.atlassian.com/git/tutorials/comparing-workflows/forking-workflow


## Installation

After having `git clone`d your fork of the potto repository and having set up both `origin` and `upstream`
remotes:

1.  Have your database up and running. If you are using the docker compose file that comes with the potto repository,
    you can run:

    ```shell
    docker compose -f docker/compose.dev.yaml up -d
    ```

2.  Ensure you have these environment variables set:

    ```shell
    PYGEOAPI_ROOT="/datadisk/dev/pygeoapi"
    POTTO__DATABASE_DSN="postgresql+psycopg://<user>:<password>@localhost:<port>/<db>"
    POTTO__TEST_DATABASE_DSN="postgresql+psycopg://potto:pottopass@localhost:55433/potto_test"
    POTTO__DEBUG="true"
    POTTO__UVICORN_LOG_CONFIG_FILE="/datadisk/dev/potto/uvicorn-log-config-no-db.yml"
    ```

    A good strategy is to create a `potto-dev.env` file with the variables and then load it:

    ```shell
    set -o allexport; source potto-dev.env; set +o allexport
    ```

3.  Install the [pre-commit] hooks:

    ```shell
    pre-commit install
    ```

    These will ensure that your code is properly formatted and perform some basic linting and static analysis whenever
    you try to commit changes.

4.  Install potto with [uv]:

    ```shell
    uv sync --group dev
    ```

6.  Use the `potto` CLI to initialize the database

    ```uv run potto db upgrade```


You are now ready to start working on the code.

5.  Use the `potto` CLI to start the potto web application server:

    ```shell
    uv run potto run-server
    ```


## Code formatting and static analysis

The pre-commit hook uses [ruff] and [ty] to format the code and perform linting and static analysis. These tools also
run in CI and you can run them yourself with:

```shell
uv run ruff format --check
uv run ruff check
uv run ty check
```

[ruff]: https://astral.sh/ruff
[ty]: https://docs.astral.sh/ty/


## Running tests

potto uses [pytest] and running the tests requires the existence of an additional database.

1.  Ensure you define the `POTTO__TEST_DATABASE_DSN` environment variable. Create this test database and then put
    this in your `potto-dev.env` file:

    ```shell
    POTTO__TEST_DATABASE_DSN="postgresql+psycopg://<user>:<password>@localhost:<port>/<db>"
    ```

    !!! note

        Don't forget to export the contents of your `potto-dev.env` file before running the tests

2.  Run tests with:

    ```shell
    uv run pytest
    ```

[pytest]: https://docs.pytest.org/en/stable/


### API linting


potto uses [spectral] for enforcing API style and security-related rules. This tool runs in CI and you can also run
it yourself in one of two ways:

[spectral]: https://stoplight.io/open-source/spectral

-   by exporting the OpenAPI document to a file and then running spectral on it:

    ```shell
    uv run potto export-openapi --output potto_openapi_dev.json
    spectral lint -F info -r spectral/spectral.yaml potto_openapi_dev.json
    ```

-   by using the dynamically generated openapi whenever the potto server is running. As an example, assuming it is
    running on `localhost:3001`:

    ```shell
    spectral lint -r spectral/spectral.yaml http://localhost:3001/api/openapi.json
    ```

!!! note

    Using spectral locally requires that you first install it with something like:

    ```shell
    npm install -g @stoplight/spectral-cli
    ```

    Check the [spectral installation docs](https://docs.stoplight.io/docs/spectral/b8391e051b7d8-installation) for more detail.


### Running official OGC test suites

potto's CI workflow uses [ogc-cite-runner] to run OGC test suites. This provides feedback on whether it
is keeping up with the OGC API standards. You can also run it locally like this:

!!! tip "TeamEngine docker image"

    potto uses the `ogccite/teamengine-beta` docker image as opposed to `ogccite/teamengine-production` because it
    contains newer versions of the OGC test suites.

    This also means that the TeamEngine URL used when running ogc-cite-action ends with `/te2`
    instead of `/teamengine`.

[ogc-cite-runner]: https://osgeo.github.io/ogc-cite-runner/

-   Start TeamEngine locally by using its docker image
-   Ensure the potto server is running and properly configured:

    -   Set the following environment variables before starting the server:

        ```shell
        POTTO__BIND_HOST=0.0.0.0
        POTTO__PUBLIC_URL=http://host.docker.internal:3001
        POTTO__USE_OAS30_FIXES=true
        ```
    -   Ensure there is at least one public collection of the type you are trying to test

-   Launch ogc-cite-runner with the correct incantation for the test suite you wish to test

For example:

```shell

# pull TeamEngine docker image
docker pull ogccite/teamengine-beta:1.0-SNAPSHOT

# launch it
docker run \
    --rm \
    --detach \
    --name=teamengine \
    --add-host=host.docker.internal:host-gateway \
    --publish=9080:8080 \
    ogccite/teamengine-beta:1.0-SNAPSHOT

# have at least one public collection
uv run potto cite-testing bootstrap-ogcapi-features-1

# launch potto with a suitable configuration
set -o allexport; source potto-dev.env; set +o allexport; \
    POTTO__BIND_HOST=0.0.0.0 \
    POTTO__PUBLIC_URL=http://host.docker.internal:3001 \
    POTTO__USE_0AS30_FIXES=true \
    uv run potto run-server


# use ogc-cite-runner
# in this example we are testing OGC API - Features
uv run ogc-cite-runner execute-test-suite http://localhost:9080/te2 \
    ogcapi-features-1.0 \
    --suite-input iut http://host.docker.internal:3001/api \
    --with-failed
```

??? info "networking between the teamengine container and the host network"

    In the example above we set the URL of the implementation under test (_i.e._ the `iut` suite input) to
    be `http://host.docker.internal:3001/api`.

    Together with the `--add-host=host.docker.internal:host-gateway` flag, which is used when starting the teamengine
    docker container, this lets the running TeamEngine instance see services which are running on the docker host's
    network.

    Check the [docker engine docs](https://docs.docker.com/reference/cli/docker/container/run/#add-host) for more
    detail on this.



## Working on documentation

potto's docs are built with [zensical].

[zensical]: https://zensical.org/
