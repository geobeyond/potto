---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Use pluggable authentication, with built-in backends for local accounts and OIDC

## Context and Problem Statement

potto needs to know who is making a request, because resources have owners and may be private
([ADR-ownership]). Deployments differ widely: a small or demo server may want a handful of local accounts with
passwords, while an institutional deployment will want to integrate with an existing identity provider (Keycloak,
Azure AD, Google, ...) and not manage passwords at all.

Authentication must also be kept separate from authorization ([ADR-authz]): knowing *who* the user is must not
dictate *what* they may do.

How should potto authenticate users across these deployment types?

## Considered Options

- Pluggable authentication with two built-in backends: local accounts and OpenID Connect (OIDC)
- Local accounts only
- OIDC only, requiring an external identity provider for every deployment
- No authentication in potto; trust identity headers set by a reverse proxy

## Decision Outcome

Chosen option: "Pluggable authentication with built-in backends for local accounts and OIDC", because it covers the
zero-infrastructure case and the enterprise case without forcing either on the other, and keeps authentication
independent from the rest of the system.

The design:

- Authentication backends are starlette `AuthenticationBackend`s, installed through `AuthenticationMiddleware`, which
  resolve each connection to a `PottoUser` (or anonymous). The rest of potto only ever sees `request.user`;
- **Local backend** (`authn/backend.py::LocalAuthBackend`): users are stored by the user account manager and
  authenticated with bcrypt-hashed passwords (`UserAccountProtocol.authenticate()`). A session cookie is used for the
  browser UIs, and potto-issued HS256 bearer JWTs (`authn/jwt.py`) for API clients;
- **OIDC backend** (`authn/backend.py::OIDCAuthBackend`, `authn/oidc.py`): browser users log in through the
  authorization-code flow, API clients send an access token which is validated against the provider's JWKS (RS256).
  Users unknown to potto are provisioned just in time (`provision_oidc_user`), and scopes may be taken from a
  configurable roles claim;
- The backend is selected by configuration: setting `settings.oidc` enables OIDC, otherwise local accounts are used.
  The OIDC login/callback routes, the local `/api/auth` routes, the admin UI's auth provider
  (`webapp/admin/auth.py`) and the OpenAPI security schemes all follow the same switch;
- Whatever the backend, the result is the same `PottoUser` shape, so managers, operations and the authorization
  backend never know how the user logged in. Other components that need their own credentials, like the public event
  broker, exchange a potto session for a potto-issued token rather than talking to the identity provider
  ([ADR-public-broker]).

<!-- TODO: backend selection is currently a hardcoded if/else on settings.oidc (webapp/main.py, webapp/admin/main.py).
Decide whether to make it pluggable via an ImportString factory, like the resource managers, so third parties can add
backends (e.g. API keys, mTLS, SAML) without patching potto. -->

### Consequences

- Good, because a deployment can start with local accounts and move to OIDC without touching resources or policies;
- Good, because the rest of the codebase depends only on `PottoUser`, not on the identity provider;
- Good, because OIDC deployments delegate password handling, MFA and account lifecycle to a dedicated system;
- Bad, because potto has to maintain two login flows, two token formats and two admin auth providers;
- Bad, because only one backend can be active at a time. A deployment cannot combine local service accounts with
  OIDC users;
- Bad, because just-in-time provisioning means user records in potto can drift from the identity provider (e.g. a
  user removed from the IdP still has a potto record and owns resources).


[ADR-ownership]: xxxx-bake-resource-ownership-and-sharing-into-core-model.md
[ADR-authz]: xxxx-pluggable-authorization-with-local-and-opa.md
[ADR-public-broker]: xxxx-public-mqtt-broker-and-authorization.md
