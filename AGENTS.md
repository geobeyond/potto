# Potto — Agent Knowledge Base

This file captures architectural decisions, patterns, and non-obvious implementation details
that are useful context for AI agents working on this codebase.

---

## Environment

- Always use `uv` instead of bare `python3` or `pip`.
- Before running any `uv` command, load the dev environment:
  ```bash
  set -o allexport; source potto-dev.env; set +o allexport; uv <command>
  ```

---

## Project Layout

```
src/potto/
├── authz/          # Authorization backends (protocol + local + OPA)
├── authn/          # Authentication (OIDC provider)
├── cliapp/         # Cyclopts CLI subcommands
├── db/
│   ├── commands/   # DB write operations (create, update, delete)
│   ├── models.py   # SQLModel ORM models
│   └── queries/    # DB read operations
├── exceptions.py   # All custom exception types
├── operations/     # Business logic: check permissions, then call commands
├── schemas/        # Pydantic schemas (API, CLI, metadata, auth, etc.)
└── webapp/
    ├── admin/      # starlette-admin section
    │   ├── auth.py     # Admin auth providers (local + OIDC)
    │   ├── fields.py   # Custom starlette-admin fields
    │   ├── main.py     # PottoAdmin class + view registration
    │   └── views.py    # ModelView subclasses
    ├── api/
    │   ├── dependencies.py  # FastAPI dependencies + shared path/query param type aliases
    │   ├── responses.py     # Shared ERROR_RESPONSES dict used on every route decorator
    │   ├── tags.py          # OpenAPI tag name constants + OPENAPI_TAGS list
    │   └── routers/
    └── templates/admin/  # Overridden starlette-admin templates
```

---

## Authorization Architecture

### Two independent axes

- **Authentication** (`authn/`): local (bcrypt) or OIDC. Controlled by `settings.oidc`.
- **Authorization** (`authz/`): local (scope-based) or OPA. Controlled by `settings.opa`.

### Protocol

`authz/base.py` defines `AuthorizationBackendProtocol` — all permission checks go through
this interface. Both `LocalAuthorizationBackend` and `OPAAuthorizationBackend` implement it.

When adding a new permission:
1. Add `async can_do_thing(self, user: PottoUser | None) -> bool` to the protocol in `authz/base.py`
2. Implement in `authz/backend.py` (local: check scopes; admin-only means `PottoScope.ADMIN.value in user.scopes`)
3. Implement in `authz/opa.py` (delegate to OPA via `self._query("can_do_thing", {...})`)
4. Add a `PottoCannotDoThingException` to `exceptions.py`
5. Add an `operations/` function that checks the permission and calls the relevant command

### Admin scope

`PottoScope.ADMIN.value` is the string `"admin"`. Admin-only operations check for its presence
in `user.scopes`.

### OPA backend and local user management

`OPAAuthorizationBackend.can_create_user` always returns `False` — OPA setups do not support
creating users directly in Potto (users come from the external identity provider).

---

## Operations Pattern

`operations/` functions sit between the web/CLI layer and `db/commands/`. They:
1. Check permissions via the auth backend — raise a `PottoCannotXxxException` if denied
2. Call the relevant `db/commands/` function

**CLI is exempt**: CLI commands are admin-only by convention and call `db/commands/` directly,
bypassing the operations layer.

---

## Admin Section (starlette-admin)

### PottoAdmin (`webapp/admin/main.py`)

Extends `Admin` with:
- `mount_to()` — injects `SETTINGS` into the admin app's state so views can access it
- `_render_list()` — **fully reimplemented** (not delegating to super) to:
  - Handle `skip_list` redirect for single-instance views (redirects to detail page)
  - Compute `can_create` asynchronously and pass it as a template context variable,
    working around starlette-admin's sync-only `can_create(request)` hook
- `_render_create()` — checks `async_can_create` on the model before delegating to super
- `_render_edit()` — checks `async_can_edit` on the model before delegating to super

### Async permission hooks on views

starlette-admin's built-in permission hooks (`can_create`, `can_edit`, `can_delete`) are all
**synchronous**, which makes it impossible to call async authorization backends from them.

The pattern used in Potto to work around this:

| Hook needed | Approach |
|---|---|
| Hide/protect **edit** page | Add `async_can_edit(request) -> bool` to the view; `PottoAdmin._render_edit` checks it |
| Hide/protect **create** page + button | Add `async_can_create(request) -> bool` to the view; `PottoAdmin._render_create` checks it, and `_render_list` computes it for the template |
| Hide **row action** buttons (e.g. Edit on detail page) | Override `is_row_action_allowed(request, name)` — this IS already async in starlette-admin |

### Single-instance views (`ServerMetadataModelView`)

For models that have exactly one instance, set `skip_list = True` on the view. `PottoAdmin._render_list`
will redirect straight to the detail page of that instance.

Also override:
- `find_all` → return `[await get_the_single_instance(session)]`
- `count` → return `1`
- `find_by_pk` → return the single instance regardless of pk
- `can_create(request) -> bool` → return `False` (it's a method, not an attribute)
- `can_delete(request) -> bool` → return `False`

### Custom templates

Overriding a starlette-admin template: place a file with the same name under
`webapp/templates/admin/`. Currently overridden:

- `edit.html` — overrides `form.js` script path (workaround for starlette-admin issue #737)
- `list.html` — replaces `model.can_create(request)` with the async-computed `can_create`
  context variable

### Handling exceptions in views

`_PottoAdminModelView.handle_exception()` maps `PottoCannotXxxException` types to
`FormValidationError` so starlette-admin renders them as inline form errors rather than
500s. When adding a new exception type, add a corresponding `isinstance` branch there.

---

## CLI (`cliapp/`)

Uses **Cyclopts**. Each subcommand module defines a `cyclopts.App()` and a `launcher` function
decorated with `@app.meta.default` that handles async dispatch and settings injection.

Settings are injected as `settings: Annotated[PottoSettings, cyclopts.Parameter(parse=False)]`
and excluded from user-visible help.

### Metadata CLI

`cliapp/metadata.py` uses `ServerMetadataFlattenedUpdate` for CLI arguments (flat flags like
`--license-name`, `--point-of-contact-email`). The `update_metadata_flattened` command in
`db/commands/metadata.py` unflattens these into the nested `ServerMetadataUpdate` schema.

---

## Schemas

- `ServerMetadataUpdate` — the canonical update schema; used by both the operation layer and
  `update_metadata_flattened`. Contains `keywords_type`, `terms_of_service`, and `url` in
  addition to the nested objects.
- `ServerMetadataFlattenedUpdate` — CLI-friendly flat schema with prefixed fields
  (`license_name`, `point_of_contact_city`, etc.)
- `Title`, `MaybeDescription`, `MaybeKeywords` — localizable JSONB types that accept either
  a plain `str` or a `dict[str, str]` (multilingual). In the admin UI these are treated as
  plain strings for simplicity.

---

## FastAPI App (`webapp/api/main.py`)

### OpenAPI metadata from the database

`create_api_app_from_settings` fetches `ServerMetadata` from the DB at startup to populate the
FastAPI `title`, `description`, `contact`, and `license_info` fields. This means **the app
requires a reachable database to start**, including during `potto export-openapi`.

In CI, set `POTTO__DATABASE_DSN` before running `export-openapi` or `db upgrade`.

### Running async code from a sync factory

`create_api_app_from_settings` is synchronous but needs to `await` a DB query. A plain
`asyncio.run()` would fail when called from within uvicorn's running event loop. The workaround
is to run it in a new thread (which has no event loop):

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    api_metadata = cast(ServerMetadata, pool.submit(asyncio.run, _fetch_api_metadata(settings)).result())
```

### Fallback values for missing metadata

When `ServerMetadata` fields are unset (e.g. freshly initialized DB), placeholder fallbacks are:
- `description` → `"unknown"`
- `contact.name` → `"unknown"`
- `contact.email` → `"unknown@example.com"` (must be a valid email; `.invalid` and bare domains are rejected by pydantic)
- `contact.url`, `license.url` → `str(settings.public_url)`
- `license.name` → `"unknown"`

### Adding a new API tag

1. Add a constant to `webapp/api/tags.py`
2. Add a `{"name": THE_CONSTANT, "description": "..."}` entry to `OPENAPI_TAGS` in the same file
3. Use the constant in your router decorators: `tags=[tags.THE_CONSTANT]`

`main.py` picks up `OPENAPI_TAGS` automatically — no changes needed there.

### Suppressing a Spectral rule for a specific operation

Use an `overrides` entry in `spectral/spectral.yaml` with a JSON Pointer fragment (`~1` encodes `/`):

```yaml
overrides:
  - files:
      - "**#/paths/~1some~1path/get"
    rules:
      rule-name: off
```

---

## Key Gotchas

- `ServerMetadata` is a singleton — only one row should ever exist. `get_server_metadata()`
  in `operations/metadata.py` creates a default if none exists.
- `update_metadata` uses `model_dump(exclude_unset=True)` + `setattr`, so only explicitly
  set fields on `ServerMetadataUpdate` are written to the DB.
- starlette-admin's `can_create`, `can_edit`, `can_delete` are **methods** on the view class,
  not boolean attributes — overriding them with a bare `= False` attribute breaks calling code.
- `CollectionField` nested data arrives in `edit()`/`create()` as a dict (or `None`/`{}`
  if all subfields were left empty). Always guard with `if data.get("field_name")` before
  constructing the nested Pydantic model.
- `docker/compose.ci.yaml` only defines the `db` service — there is no `webapp` container.
  `potto db upgrade` and `potto export-openapi` run on the CI host directly.
- Use `docker compose up --detach --wait` in CI to block until the DB healthcheck passes
  before running any commands against it.
- `ServerMetadata.to_potto()` guards `license` and `data_provider` for `None`, but
  `point_of_contact` must also be guarded — it is nullable and will be `None` on a freshly
  created default metadata row.
