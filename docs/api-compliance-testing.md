---
icon: lucide/shield-check
---

# API compliance testing

Beyond the regular pytest suite (see [Running tests]), potto's OpenAPI document and running instances are checked
by three complementary, more specialized tools. Each catches a different class of problem, and all three run in
CI, on every pull request:

| Tool | Checks |
| --- | --- |
| [spectral] | API style and security conventions on the OpenAPI document itself |
| [ogcapi-registry] | Whether the API actually implements what it declares to conform to |
| [ogc-cite-runner] | Official OGC compliance test suites (TeamEngine) |

[Running tests]: development.md#running-tests


## Spectral: API style and security linting

potto uses [spectral] to lint the OpenAPI document itself against a custom ruleset (`spectral/spectral.yaml`),
catching style and security-related issues - things like inconsistent naming, missing security schemes, or
malformed parameter definitions.

The ruleset is a light customization of the official [OWASP API Security Top 10] Spectral ruleset (vendored under
`spectral/owasp-top10/`), which checks for the kind of API design mistakes behind OWASP's well-known list of API
vulnerability classes - broken authentication, excessive data exposure, security misconfiguration, and so on. This
matters because it's a standardized, actively-maintained set of checks that catches whole categories of security
mistakes before they ever reach a running instance, rather than relying on every contributor to independently
remember them. potto's `spectral/spectral.yaml` extends this base ruleset with:

- a handful of `owasp:api4:2019-*` rules turned off, covering the "Lack of Resources & Rate Limiting" category -
  these require annotating essentially every schema field with explicit `maxLength`/`format`/`maximum`/`maxItems`
  constraints and documenting `429` rate-limit responses, neither of which potto does today
- `array-items` turned off, since the built-in rule doesn't yet recognize `prefixItems` as a valid alternative to
  `items` for describing array contents
- three targeted `overrides` that disable the "endpoint requires authentication" checks for `/login`, `/conformance`,
  and `/health` specifically, since those are meant to be public

[OWASP API Security Top 10]: https://owasp.org/www-project-api-security/

!!! note "The rate-limiting and constraint rules are meant to come back"

    The `owasp:api4:2019-*` rules are turned off because potto doesn't yet declare resource limits or rate
    limiting, not because they don't matter - lack of both is itself an OWASP API Security Top 10 category. As
    development progresses and potto adds schema-level size/format constraints and rate limiting, these rules
    will be re-enabled in the near future rather than staying off indefinitely - tracked in
    [geobeyond/potto#48](https://github.com/geobeyond/potto/issues/48).

To run it yourself against the dev stack, first make sure it's running (see [Installation]), then:

```shell
npm install -g @stoplight/spectral-cli
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    exec -T potto uv run potto openapi export > potto_openapi_dev.json
spectral lint -F info -r spectral/spectral.yaml potto_openapi_dev.json
```

Or, since the OpenAPI document is also served dynamically, point spectral straight at the running instance instead:

```shell
spectral lint -r spectral/spectral.yaml http://localhost:3001/api/openapi.json
```

!!! note

    Installing spectral locally requires Node.js. Check the
    [spectral installation docs](https://docs.stoplight.io/docs/spectral/b8391e051b7d8-installation) for detail.

[Installation]: development.md#installation
[spectral]: https://stoplight.io/open-source/spectral


## ogcapi-registry: conformance validation

Declaring an OGC API conformance class is easy - actually implementing everything it requires is another matter.
`potto openapi validate` uses the [ogcapi-registry] library to fetch a running instance's `/openapi.json` and
`/conformance` documents and cross-check that the OpenAPI document really implements what the server claims to
conform to.

To run it yourself against the dev stack (already running - see [Installation]):

```shell
docker compose \
    --env-file docker/local.env \
    -f docker/compose.dev.yaml \
    exec -ti \
    uv run potto openapi validate
```

This defaults to validating `http://localhost:3001/api`, matching the dev stack's published port. Pass
`--potto-api-base-url` to point it elsewhere.

[ogcapi-registry]: https://github.com/geobeyond/ogcapi-registry


## ogc-cite-runner: official OGC test suites

[ogc-cite-runner] runs the official OGC CITE (Compliance & Interoperability Testing & Evaluation) test suites via
TeamEngine. This is the most thorough of the three checks - it exercises a live instance the same way the official
OGC compliance program would, and is the closest thing to ground truth on whether potto actually implements a
given OGC API standard.

!!! tip "TeamEngine docker image"

    potto uses the `ogccite/teamengine-beta` docker image as opposed to `ogccite/teamengine-production` because it
    contains newer versions of the OGC test suites. This also means the TeamEngine URL ends with `/te2` instead of
    `/teamengine`.

To run it yourself, launch TeamEngine and a suitably-configured potto process by hand:

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

??? info "Networking between the TeamEngine container and the host network"

    In the example above, the URL of the implementation under test (the `iut` suite input) is
    `http://host.docker.internal:3001/api`.

    Together with the `--add-host=host.docker.internal:host-gateway` flag used when starting the TeamEngine
    container, this lets the running TeamEngine instance see services running on the docker host's network.

    Check the [docker engine docs](https://docs.docker.com/reference/cli/docker/container/run/#add-host) for more
    detail.

[ogc-cite-runner]: https://osgeo.github.io/ogc-cite-runner/
