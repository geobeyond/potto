---
icon: lucide/hammer
---

# Development

## Quickstart

potto's recommended dev workflow is fully container-based: `docker compose` builds the potto image, starts
PostgreSQL/PostGIS (the `db` and `test-db` services) and the potto server itself, and syncs local source code
changes live into the running container.

!!! note

    This is the recommended setup, not the only one. If you'd rather run PostgreSQL and the potto server directly
    on your host, you can do so - just adapt the environment variables described in `src/potto/config.py`
    accordingly. The rest of this guide assumes the container-based workflow.

1.  Create a `docker/local.env` file (gitignored, one per machine) pointing at wherever you keep your local
    development data:

    ```shell
    echo 'POTTO_DATA_ROOT="/path/to/your/local/data/directory"' > docker/local.env
    ```

2.  Start the stack:

    ```shell
    CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') \
        CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
        docker compose \
            --env-file docker/local.env \
            -f docker/compose.dev.yaml \
            up --watch --build
    ```

    potto is now available at <http://localhost:3001>. See [Rebuilding the docker image] for details on how
    code changes get picked up while the stack is running.

[Rebuilding the docker image]: #rebuilding-the-docker-image



## Contribution guidelines

Read the contribution guidelines, to be added...


## Setup

Contributing to potto requires a couple of pre-requisites to be met:

You should be running a linux distribution. Development might also be possible on other OS, but you'll be mostly
on your own with regard to how to set up your working environment.

Additionally, the following tools need to be installed on your machine:

-  [git]
-  [pre-commit]
-  [uv]
-  [Docker] and [docker compose]

Please refer to each tool's own documentation for how to get it installed.

The potto-provided docker compose file takes care of running [PostgreSQL]/[PostGIS] (both a `db` and a `test-db`
service) as well as the potto server itself, so there is no need to install those separately.

[Docker]: https://docs.docker.com/engine/
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

1.  Create a `docker/local.env` file (gitignored, one per machine) pointing at wherever you keep your local
    development data:

    ```shell
    echo 'POTTO_DATA_ROOT="/path/to/your/local/data/directory"' > docker/local.env
    ```

2.  Start the dev stack - this builds the potto image, brings up `db` and `test-db`, and starts the potto server
    itself, syncing local source code changes into the running container:

    ```shell
    CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
        docker compose --env-file docker/local.env -f docker/compose.dev.yaml up --watch --build
    ```

3.  Install the [pre-commit] hooks:

    ```shell
    pre-commit install
    ```

    These will ensure that your code is properly formatted and perform some basic linting and static analysis whenever
    you try to commit changes.

4.  Install potto with [uv]. This is needed for host-side tooling, such as tests and linters, even though the
    potto server itself now runs inside a container:

    ```shell
    uv sync --group dev
    ```

5.  Use the `potto` CLI to initialize the database, running it inside the already-running `potto` container so it
    picks up the right database connection settings automatically:

    ```shell
    docker compose \
        --env-file docker/local.env \
        -f docker/compose.dev.yaml \
        exec potto uv run potto db upgrade
    ```

    !!! note

        `--env-file docker/local.env` is required here too, even though the container is already running - it's
        needed for `docker compose` itself to resolve `POTTO_DATA_ROOT` when it re-reads the compose file to
        find the `potto` service.

You are now ready to start working on the code. potto is available at <http://localhost:3001>.


## Rebuilding the docker image

Usually potto's development docker images are built remotely, when the continuous integration pipeline is run.
This process is triggered everytime the source code repository's `main` branch has changes merged in. The newly built
image is then pushed to potto's docker registry at ghcr.io/geobeyond/potto/potto.

While the dev stack is running with `--watch` (as shown in [Installation]), most day-to-day changes are handled
automatically: `src/potto` is synced live, and changes to `pyproject.toml` or `uv.lock` (for example, after
running `uv add` to bring in a new dependency) trigger an automatic rebuild.

The one case `--watch` doesn't cover is changes to `docker/Dockerfile` itself, since it isn't a watched path. If
you edit the `Dockerfile`, force a rebuild yourself with:

```shell
CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
    docker compose --env-file docker/local.env -f docker/compose.dev.yaml build potto
```

The built image is tagged after the current `git` branch (slashes are replaced with `-`, since docker image tags
cannot contain them). Use it only during your own local development.

[Installation]: #installation


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

potto uses [pytest] for testing. The production `potto` image does not install the `dev` dependency group . Testing
instead runs through two dedicated containers, each built from the `potto` image
(via [docker compose additional_contexts]), with just what that kind of testing needs layered on top.
Both are behind their own [docker compose profile], so neither is part of the default dev stack.

[docker compose profile]: https://docs.docker.com/reference/compose-file/profiles/
[docker compose additional_contexts]: https://docs.docker.com/reference/compose-file/build/#additional_contexts

Non-e2e tests (unit and integration) run via the `potto-test` service (profile `test`), which layers on
`uv sync --group dev`. `tests/` is synced live via `--watch` (same as `src/potto`), so edits to test files are
picked up without a rebuild:

```shell
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    --profile test \
    run --rm potto-test

# only run the integration tests
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    --profile test run --rm \
    potto-test uv run pytest -m integration
```

End-to-end tests use [playwright] and run via the `potto-e2e` service (profile `e2e`), which layers on the same
`uv sync --group dev` plus Playwright's browser and its OS-level dependencies.

The container is self-contained:
it spins up its own throwaway `potto run-server` process and a headless browser internally, both talking only to
`test-db`.

```shell
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    --profile e2e \
    run --rm potto-e2e
```

??? tip "Watching a test run headed"

    By default the browser runs headless inside the container. To watch it run with a real, visible browser
    window, forward your X11 display into the container as one-off flags (this is opt-in per run, not part of
    the service's default config):

    ```shell
    xhost +local:docker   # once per session: let containers reach your X server

    docker compose \
        --env-file docker/local.env \
        -f docker/compose.dev.yaml \
        --profile e2e \
        run --rm \
        -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
        potto-e2e uv run pytest -m e2e --headed
    ```

    `xhost +local:docker` loosens X access control for local Unix-socket clients - reasonable on a single-user
    dev machine, but worth being aware of.

??? tip "Getting a Playwright trace for a failed run"

    Traces are wired into fixtures in `tests/conftest.py`, gated behind pytest-playwright's
    `--tracing` flag (off by default), and written to `test-results/`, which is bind-mounted from the repo root
    so files survive after the (ephemeral, `--rm`) container exits:

    ```shell
    docker compose \
        --env-file docker/local.env \
        -f docker/compose.dev.yaml \
        --profile e2e \
        run --rm \
        potto-e2e uv run pytest -m e2e --tracing=retain-on-failure
    ```

    Open the resulting `test-results/*-trace.zip` at <https://trace.playwright.dev> - Playwright's web-based
    trace viewer.

[playwright]: https://playwright.dev/python/
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
POTTO__DATABASE_DSN="postgresql+psycopg://potto:pottopass@localhost:55432/potto" \
    POTTO__BIND_HOST=0.0.0.0 \
    POTTO__PUBLIC_URL=http://host.docker.internal:3001 \
    POTTO__USE_OAS30_FIXES=true \
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
