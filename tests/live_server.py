"""Local pytest plugin managing the live server used by e2e tests.

Registered from conftest.py via `pytest_plugins`. Kept separate because it
bundles together everything needed to either spin up a throwaway server
against the test database, or point at an already-running one (e.g.
staging) via `--base-url`.
"""

import dataclasses
import os
import subprocess
import time
import uuid

import httpx
import jwt
import pytest

from potto import config
import sqlmodel

_LIVE_SERVER_USERNAME = "e2e-admin"
_LIVE_SERVER_PASSWORD = "e2e-testpass"


def pytest_addoption(parser):
    parser.addoption(
        "--user-name",
        action="store",
        default=None,
        help="Username of an existing admin user, for e2e tests",
    )
    parser.addoption(
        "--user-password",
        action="store",
        default=None,
        help="Password of an existing admin user, for e2e tests",
    )
    parser.addoption(
        "--live-server-port",
        action="store",
        type=int,
        default=3002,
        help="Port to bind the locally-managed live server to, for e2e tests",
    )


@dataclasses.dataclass
class LiveServer:
    base_url: str
    username: str
    password: str


def _wait_for_live_server(
    process: subprocess.Popen, base_url: str, timeout_seconds: float = 30
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Live server process exited early with code {process.returncode}"
            )
        try:
            httpx.get(base_url, timeout=1)
        except httpx.TransportError:
            time.sleep(0.5)
        else:
            return
    raise RuntimeError(f"Live server at {base_url} did not become ready in time")


@pytest.fixture(scope="session")
def live_server(request):
    """Runs `potto run-server` against the test database, for e2e tests.

    Skipped entirely when `--base-url` is passed, which means the e2e tests
    are meant to run against an already-running server (e.g. staging). Its
    stdout/stderr are inherited from the pytest process, rather than
    redirected to a file, so pytest's own output capturing surfaces them
    when a test fails.
    """
    if request.config.getoption("--base-url"):
        yield None
        return

    live_settings = config.get_settings()
    live_settings.database_dsn = live_settings.test_database_dsn
    sync_engine = live_settings.get_sync_db_engine()
    sqlmodel.SQLModel.metadata.create_all(sync_engine)

    port = request.config.getoption("--live-server-port")
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "POTTO__DATABASE_DSN": live_settings.database_dsn.unicode_string(),
        "POTTO__BIND_HOST": "127.0.0.1",
        "POTTO__BIND_PORT": str(port),
        "POTTO__PUBLIC_URL": base_url,
        "POTTO__UVICORN_NUM_WORKERS": "1",
    }
    # Creating the admin user via the CLI, rather than an in-process async
    # `create_user()` call, avoids touching pytest-asyncio's own event loop
    # management for the rest of the test session.
    subprocess.run(
        [
            "potto",
            "user",
            "create",
            _LIVE_SERVER_USERNAME,
            "--email",
            "e2e-admin@test.test",
            "--scope",
            "admin",
            "--password-stdin",
        ],
        input=_LIVE_SERVER_PASSWORD,
        text=True,
        env=env,
        check=True,
    )

    process = subprocess.Popen(["potto", "run-server"], env=env)
    try:
        _wait_for_live_server(process, base_url)
        yield LiveServer(
            base_url=base_url,
            username=_LIVE_SERVER_USERNAME,
            password=_LIVE_SERVER_PASSWORD,
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        sqlmodel.SQLModel.metadata.drop_all(sync_engine)


@pytest.fixture(scope="session")
def base_url(live_server, request):
    if explicit_base_url := request.config.getoption("--base-url"):
        return explicit_base_url
    return live_server.base_url


@pytest.fixture(scope="session")
def auth_credentials(request, live_server):
    username = request.config.getoption("--user-name")
    password = request.config.getoption("--user-password")
    if username and password:
        return username, password
    if live_server is not None:
        return live_server.username, live_server.password
    pytest.skip(
        "Authentication credentials not provided. Pass the --user-name "
        "and --user-password CLI options when using --base-url."
    )


@pytest.fixture
def api_client(base_url, auth_credentials):
    """An httpx.Client authenticated against the live server's API.

    This is only meant as test-data setup for e2e tests exercising the web
    UI - the API itself already has its own, more thorough test coverage.
    """
    username, password = auth_credentials
    with httpx.Client(base_url=base_url) as client:
        login_response = client.post(
            "/api/login", data={"username": username, "password": password}
        )
        login_response.raise_for_status()
        token = login_response.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        # Decoded without verification - we already trust a token we just
        # obtained via a successful login, and don't have the server's
        # signing secret when targeting a remote (e.g. staging) server.
        client.owner_id = jwt.decode(token, options={"verify_signature": False})["sub"]
        yield client


@pytest.fixture
def e2e_collection(api_client):
    """Creates a collection via the API, for e2e tests to check the UI renders it."""
    payload = {
        "resource_identifier": f"e2e-test-{uuid.uuid4().hex[:8]}",
        "owner_id": api_client.owner_id,
        "collection_type": "feature",
        "title": "E2E test collection",
        "providers": {
            "feature": {
                "provider_name": "pygeoapi",
                "config": {
                    "python_callable": (
                        "potto.pygeoapi_providers.PygeoapiConfigWktFeatureProvider"
                    ),
                    "options": {},
                    "data": {
                        "features": [
                            {
                                "id": 1,
                                "geometry": "POINT (-75 45)",
                                "properties": {"value": 1},
                            }
                        ]
                    },
                },
            }
        },
    }
    create_response = api_client.post("/api/collections", json=payload)
    create_response.raise_for_status()
    collection = create_response.json()
    yield collection
    api_client.delete(f"/api/collections/{collection['id']}").raise_for_status()
