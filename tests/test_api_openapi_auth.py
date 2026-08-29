from urllib.parse import (
    urljoin,
    urlparse,
)

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from potto import config
from potto.webapp.api import dependencies
from potto.webapp.api.main import create_api_app_from_settings

pytestmark = pytest.mark.integration


def test_local_login_reachable_at_resolved_token_url(admin_user, webapp_test_client):
    """Regression test for issue #56.

    Swagger UI resolves the local password flow's relative tokenUrl against
    the OpenAPI document's servers[0].url per RFC 3986. If that server URL
    is missing a trailing slash, the resolved URL drops the "/api" mount
    prefix and points at a route that doesn't exist, breaking the docs'
    "Authorize" popup for the local auth backend.
    """
    schema = webapp_test_client.get("/api/openapi.json").json()
    server_url = schema["servers"][0]["url"]
    token_url = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"][
        "flows"
    ]["password"]["tokenUrl"]
    resolved_path = urlparse(urljoin(server_url, token_url)).path

    assert resolved_path == "/api/login"

    response = webapp_test_client.post(
        resolved_path,
        data={"username": "test-admin", "password": "testpass"},
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_oidc_docs_show_oidc_security_scheme(db, settings):
    """Regression test for issue #56.

    dependency_overrides swaps get_current_user's runtime dependency for an
    OIDC-scheme variant, but that has no effect on the OpenAPI schema FastAPI
    generates from routes' static, decoration-time dependency tree. Without
    the fix, /docs in OIDC mode always advertised the local password flow
    (tokenUrl "login"), pointing at a route that doesn't even exist when OIDC
    is enabled, since auth.router is only mounted in local mode.
    """
    settings.oidc = config.OIDCSettings(
        issuer="https://idp.example.test",
        client_id="potto",
        client_secret=SecretStr("secret"),
    )
    api_app = create_api_app_from_settings(settings)
    api_app.dependency_overrides[dependencies.get_settings] = lambda: settings

    with TestClient(api_app) as client:
        schema = client.get("/openapi.json").json()

    security_schemes = schema["components"]["securitySchemes"]
    assert "OAuth2PasswordBearer" not in security_schemes
    flow = security_schemes["OAuth2AuthorizationCodeBearer"]["flows"][
        "authorizationCode"
    ]
    assert flow["authorizationUrl"] == "https://idp.example.test/authorize"
    assert flow["tokenUrl"] == "https://idp.example.test/token"

    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for requirement in operation.get("security") or []:
                assert "OAuth2PasswordBearer" not in requirement
