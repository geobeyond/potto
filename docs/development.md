---
icon: lucide/hammer
---

# Development

## Quickstart

potto's recommended dev workflow is fully container-based: `docker compose` builds the potto image, starts it
and its dependencies , and syncs local source code changes live into the running container.

!!! note

    This is the recommended setup, not the only one. If you'd rather run PostgreSQL and the potto server directly
    on your host, you can do so - just adapt the environment variables described in `src/potto/config.py`
    accordingly. The rest of this guide assumes the container-based workflow.

1.  Create a `docker/local.env` file (gitignored, one per machine) pointing at wherever you keep your local
    development data:

    ```shell
    echo 'POTTO_DATA_ROOT="/path/to/your/local/data/directory"' > docker/local.env
    ```

    Then add the pub/sub secrets to it, as described in [Pub/Sub secrets].

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

Contributing to potto requires a couple of pre-requisites to be met. You should be running a linux distribution.
Development might also be possible on other OS, but you'll be mostly on your own with regard to how to set up your
working environment. Additionally, the following tools need to be installed on your machine:

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

1. As mentioned above, start by opening an issue describing the problem. Ideally, you'd get some feedback from
   the potto devs before you start working on it
2. Fork potto's repo
3. Clone your fork locally
4. Create a new branch
5. Make changes to the code and add relevant tests
6. Open a Pull Request (PR) to get the changes integrated into the main potto repository
7. Monitor the status of the CI workflow and ensure it passes

    !!! warning

        There is a high likelyhood that potto team will not consider your PR if its associated CI workflow is not
        passing.

8. Follow the PR review process, responding to any comments or change requests
9. Rejoice when your PR is finally merged :smile: :tada:

[forking workflow]: https://www.atlassian.com/git/tutorials/comparing-workflows/forking-workflow


## Installation

After having `git clone`d your fork of the potto repository and having set up both `origin` and `upstream`
remotes:

1.  Create a `docker/local.env` file (gitignored, one per machine) pointing at wherever you keep your local
    development data:

    ```shell
    echo 'POTTO_DATA_ROOT="/path/to/your/local/data/directory"' > docker/local.env
    ```

    Then add the pub/sub secrets to it, as described in [Pub/Sub secrets].

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
        exec potto uv run potto postgis-manager upgrade
    ```

    !!! note

        `--env-file docker/local.env` is required here too, even though the container is already running - it's
        needed for `docker compose` itself to resolve `POTTO_DATA_ROOT` when it re-reads the compose file to
        find the `potto` service.

You are now ready to start working on the code. potto is available at <http://localhost:3001>.


## Using the potto CLI

Since the development workflow happens inside a running docker compose stack, you need to prefix commands that are
targeting the potto CLI with the appropriate docker-related incantation. Moreover, because potto also uses uv, it
also needs to be part of the incantation:

```shell
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    exec -ti potto \
    uv run \
    potto <cli-command>
```

The benefit of this is being able to enjoy a fully isolated local development setup.

You can also just get a shell inside the running container:

```shell
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    exec -ti potto bash
```


## Pub/Sub

The dev stack runs potto's public MQTT broker in the `potto-broker` service (see
[ADR-0018](decisions/0018-public-mqtt-broker-and-authorization.md)). It has two listeners:

- a public listener, published on the host at `localhost:11884`, where external clients subscribe to events;
- an internal listener on port `1885`, reachable only from inside the compose network, where potto's worker
  publishes events by authenticating with a shared secret.

### Pub/Sub secrets

The pub/sub services need a token signing key pair and a publisher password. Each developer generates their own and
keeps them in `docker/local.env`, next to `POTTO_DATA_ROOT`, so they are never committed:

| Variable in `docker/local.env`    | What it is                                               | Given to                     |
|-----------------------------------|----------------------------------------------------------|------------------------------|
| `POTTO_PUBSUB_TOKEN_SIGNING_KEY`  | PEM-encoded Ed25519 private key for signing client tokens | `potto`, `potto-cite`        |
| `POTTO_PUBSUB_TOKEN_PUBLIC_KEY`   | The matching PEM-encoded public key                       | `potto-broker`               |
| `POTTO_PUBSUB_PUBLISHER_PASSWORD` | Shared secret for publishing to the broker               | `potto-worker`, `potto-broker` |

Generate them and append them to `docker/local.env` with:

```shell
key=$(openssl genpkey -algorithm ed25519)
{
    printf 'POTTO_PUBSUB_TOKEN_SIGNING_KEY="%s"\n' "${key}"
    printf 'POTTO_PUBSUB_TOKEN_PUBLIC_KEY="%s"\n' "$(printf '%s\n' "${key}" | openssl pkey -pubout)"
    printf 'POTTO_PUBSUB_PUBLISHER_PASSWORD="%s"\n' "$(openssl rand -hex 24)"
} >> docker/local.env
```

The keys span several lines, which `docker compose` accepts in an env file as long as they are wrapped in double
quotes, as above.

!!! note "These are passed as compose secrets, not as environment variables"

    `docker compose` reads these values from `docker/local.env` (hence the `--env-file` flag in every command of this
    guide) and hands them to the containers as compose secrets: files mounted under `/run/secrets`, only into the
    services listed above. They never appear in any container's environment, just as in a production deployment
    - see [Configuration](configuration.md) for how potto reads settings from `/run/secrets`.

    If one of the variables is missing, `docker compose` refuses to start the services that need it, e.g.
    `environment variable "POTTO_PUBSUB_PUBLISHER_PASSWORD" required by secret "potto_pubsub-publisher-password" is
    not set`. Other services, such as `potto-test`, are not affected.

[Pub/Sub secrets]: #pubsub-secrets

### Subscribing to events

To subscribe to events, get a token and connect with any MQTT 3.1.1 client, such as the `amqtt_sub` CLI that
ships with amqtt:

```shell
ACCESS_TOKEN=$(curl -s -X POST http://localhost:3001/api/login \
    -d username=<username> -d password=<password> | jq -r .access_token)
curl -s -X POST http://localhost:3001/api/pubsub/token -H "Authorization: Bearer ${ACCESS_TOKEN}"

# events for resources that you are allowed to see
uv run amqtt_sub --url "mqtt://<user_id>:<token>@localhost:11884" -t "users/<user_id>/#"

# events for public resources, no authentication needed
uv run amqtt_sub --url "mqtt://localhost:11884" -t "public/#"
```

See [Pub/Sub](pubsub.md) for how pub/sub works from a client's perspective, and for the broker's configuration.


## Deploying OCI processes

Deploying a process whose execution unit is an OCI image means pulling that image with a container engine. potto's
worker does this through the Docker API, which is offered both by Docker and by [podman]. The dev stack does not
give the worker access to any engine by default. It is opt-in, via the `docker/compose.container-engine.yaml`
overlay.

The overlay is meant for a **rootless** engine, e.g. rootless podman. Whoever can use an engine's socket can run
containers with the privileges of the engine's user, so mounting the socket of a rootful engine, such as
`/var/run/docker.sock`, would give the worker root access on the host. With a rootless engine, the worker only gets
the privileges of the unprivileged user that runs the engine.

!!! warning "potto treats the engine's image store as its own"

    Undeploying a process deletes its image once no other potto process uses it, including the image's upstream
    name (e.g. `docker.io/library/alpine:3.20`). Images pulled into the same store by something other than potto
    may thus be deleted. In a shared environment, run the engine as a dedicated user.

### Setting up rootless podman

1.  Install podman and enable its Docker-compatible API socket for your user:

    ```shell
    systemctl --user enable --now podman.socket
    ```

2.  Find out the socket's path and its group id:

    ```shell
    socket="${XDG_RUNTIME_DIR}/podman/podman.sock"
    ls -l "${socket}"
    stat -c %g "${socket}"
    ```

    The worker container's user reaches the socket through that group, so the socket must be group-accessible
    (`srw-rw----`). If it is not, set its mode with a drop-in for the socket unit, e.g. via
    `systemctl --user edit podman.socket`:

    ```ini
    [Socket]
    SocketMode=0660
    ```

3.  Add the socket and its group id to `docker/local.env`:

    ```shell
    {
        printf 'POTTO_CONTAINER_ENGINE_SOCKET="%s"\n' "${socket}"
        printf 'POTTO_CONTAINER_ENGINE_GID="%s"\n' "$(stat -c %g "${socket}")"
    } >> docker/local.env
    ```

4.  Add `-f docker/compose.container-engine.yaml` after `-f docker/compose.dev.yaml` in the commands of this guide,
    e.g. for starting the stack:

    ```shell
    CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') \
        CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
        docker compose \
            --env-file docker/local.env \
            -f docker/compose.dev.yaml \
            -f docker/compose.container-engine.yaml \
            up --watch --build
    ```

    The overlay applies to the `potto-worker` and `potto-test` services only, as the API server never contacts the
    engine. With it, the test suite also runs the tests that need a live engine, which are otherwise skipped.

On hosts with SELinux, the mounted socket may additionally need `security_opt: [label=disable]` on those services.

### Image registries

Images must be referenced by their fully qualified name, including their registry (e.g.
`docker.io/library/alpine:3.20`, not `alpine:3.20`). Which registries can be used, and how to authenticate to them,
is part of the job manager's configuration:

| Setting                                                     | What it is                                                                                    |
|-------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `POTTO__JOB_MANAGER__SETTINGS_MODEL__OCI__ALLOWED_REGISTRIES`   | JSON list of registries processes may use, e.g. `["docker.io", "ghcr.io"]`. Unset means any |
| `POTTO__JOB_MANAGER__SETTINGS_MODEL__OCI__REGISTRY_CREDENTIALS` | JSON list of `{"registry", "username", "password"}` objects                                 |

Registries without credentials use the engine's own configuration (e.g. `podman login`, or credential helpers). As
the credentials are secret, pass them in a file named `potto__job_manager__settings_model__oci__registry_credentials`
under `/run/secrets`, e.g. as a compose secret, rather than as an environment variable.

Creating processes requires the `process:creator` scope (or being an admin), since anyone who can create a process
can make potto pull, and later run, any image from the allowed registries.

[podman]: https://podman.io/


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
CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') \
    CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
    docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    --profile test \
    run --rm potto-test

# only run the integration tests
CURRENT_GIT_BRANCH=$(git branch --show-current | tr '/' '-') \
    CURRENT_GIT_COMMIT=$(git rev-parse --short HEAD) \
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


### API linting and compliance testing

Beyond this test suite, potto's OpenAPI document and running instances are also checked with spectral,
ogcapi-registry, and ogc-cite-runner - see [API compliance testing] for what each does and how to run them
against the dev stack.

The OGC CITE suite has its own profile-gated service too, `potto-cite-runner` (profile `cite`), alongside a
dedicated `cite-db`, `potto-cite-bootstrap` and `potto-cite` server - see [API compliance testing] for the
one-line command that brings the whole thing up and runs it.

[API compliance testing]: api-compliance-testing.md


## Working on documentation

potto's docs are built with [zensical].

[zensical]: https://zensical.org/
