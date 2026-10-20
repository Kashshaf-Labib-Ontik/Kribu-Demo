from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWK
from jwt.exceptions import PyJWKClientConnectionError

from app.core.config import Settings
from app.identity.contracts import CurrentUser
from app.identity.dependencies import get_current_user, get_tenant_session, get_token_verifier
from app.identity.errors import (
    IdentityNotProvisionedError,
    IdentityProviderUnavailableError,
    InvalidAccessTokenError,
)
from app.identity.models import Tenant, UserProfile
from app.identity.service import get_identity_profile
from app.identity.tokens import OidcTokenVerifier
from app.main import app

ISSUER = "http://issuer.test/realms/kribu-demo"
AUDIENCE = "kribu-api"
TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def create_token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT_ID,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "preferred_username": "mike",
        "tenant_id": str(TENANT_ID),
        "department": "engineering",
        "realm_access": {"roles": ["employee"]},
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"})


def create_verifier() -> OidcTokenVerifier:
    settings = Settings(
        _env_file=None,
        oidc_issuer_url=ISSUER,
        oidc_jwks_url="http://jwks.test/certs",
        oidc_audience=AUDIENCE,
        oidc_clock_skew_seconds=0,
    )
    verifier = OidcTokenVerifier(settings)
    verifier._jwks_client.get_signing_key_from_jwt = Mock(  # type: ignore[method-assign]
        return_value=PyJWK.from_dict(
            jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
        )
    )
    return verifier


@pytest.mark.asyncio
async def test_valid_token_builds_trusted_current_user() -> None:
    current_user = await create_verifier().verify(create_token())

    assert current_user.subject_id == SUBJECT_ID
    assert current_user.tenant_id == TENANT_ID
    assert current_user.username == "mike"
    assert current_user.roles == frozenset({"employee"})
    assert current_user.department == "engineering"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "http://wrong-issuer.test"},
        {"aud": "wrong-audience"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"tenant_id": "not-a-uuid"},
        {"sub": ""},
        {"realm_access": {"roles": []}},
    ],
)
async def test_invalid_token_claims_are_rejected(claim_overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidAccessTokenError, match="invalid or expired"):
        await create_verifier().verify(create_token(**claim_overrides))


@pytest.mark.asyncio
async def test_token_with_invalid_signature_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": SUBJECT_ID,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "preferred_username": "mike",
            "tenant_id": str(TENANT_ID),
            "realm_access": {"roles": ["employee"]},
        },
        OTHER_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    with pytest.raises(InvalidAccessTokenError, match="invalid or expired"):
        await create_verifier().verify(token)


def test_identity_endpoint_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/identity/me", headers={"X-Correlation-ID": "identity-test"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["code"] == "authentication_required"
    assert response.json()["correlation_id"] == "identity-test"


def test_identity_endpoint_returns_provisioned_profile() -> None:
    current_user = CurrentUser(
        subject_id=SUBJECT_ID,
        tenant_id=TENANT_ID,
        username="mike",
        roles=frozenset({"employee"}),
        department="engineering",
    )
    tenant = Tenant(id=TENANT_ID, slug="kribu-demo", name="KRIBU Demo Software")
    profile = UserProfile(
        id=UUID(SUBJECT_ID),
        tenant_id=TENANT_ID,
        external_subject=SUBJECT_ID,
        username="mike",
        display_name="Mike Rahman",
        department="engineering",
        is_active=True,
    )
    result = Mock()
    result.one_or_none.return_value = (profile, tenant)
    session = AsyncMock()
    session.execute.return_value = result

    async def tenant_session_override() -> object:
        yield session

    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_tenant_session] = tenant_session_override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/identity/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "user_id": SUBJECT_ID,
        "subject_id": SUBJECT_ID,
        "username": "mike",
        "display_name": "Mike Rahman",
        "tenant_id": str(TENANT_ID),
        "tenant_slug": "kribu-demo",
        "tenant_name": "KRIBU Demo Software",
        "department": "engineering",
        "roles": ["employee"],
    }


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT_ID,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "preferred_username": "mike",
        "tenant_id": str(TENANT_ID),
        "realm_access": {"roles": ["employee"]},
    }
    claims.update(overrides)
    return claims


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        jwt.encode(_claims(), "shared-secret-of-at-least-32-bytes!!", algorithm="HS256"),
        jwt.encode(_claims(), None, algorithm="none"),
        create_token(tenant_id=None),
        jwt.encode(
            {key: value for key, value in _claims().items() if key != "tenant_id"},
            PRIVATE_KEY,
            algorithm="RS256",
            headers={"kid": "test-key"},
        ),
    ],
    ids=["hs256", "alg-none", "null-tenant", "missing-tenant"],
)
async def test_tokens_with_wrong_algorithm_or_missing_tenant_are_rejected(token: str) -> None:
    with pytest.raises(InvalidAccessTokenError):
        await create_verifier().verify(token)


@pytest.mark.asyncio
async def test_jwks_outage_is_a_service_error_not_an_invalid_token() -> None:
    verifier = create_verifier()
    verifier._jwks_client.get_signing_key_from_jwt = Mock(  # type: ignore[method-assign]
        side_effect=PyJWKClientConnectionError("Fail to fetch data from the url")
    )

    with pytest.raises(IdentityProviderUnavailableError):
        await verifier.verify(create_token())


def test_jwks_outage_returns_503_problem() -> None:
    verifier = create_verifier()
    verifier._jwks_client.get_signing_key_from_jwt = Mock(  # type: ignore[method-assign]
        side_effect=PyJWKClientConnectionError("Fail to fetch data from the url")
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/identity/me", headers={"Authorization": f"Bearer {create_token()}"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["code"] == "identity_provider_unavailable"
    assert "WWW-Authenticate" not in response.headers


def _session_returning(row: object) -> AsyncMock:
    result = Mock()
    result.one_or_none.return_value = row
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_unprovisioned_or_inactive_identity_is_forbidden() -> None:
    user = CurrentUser(
        subject_id=SUBJECT_ID, tenant_id=TENANT_ID, username="mike", roles=frozenset({"employee"})
    )

    with pytest.raises(IdentityNotProvisionedError):
        await get_identity_profile(_session_returning(None), user)


@pytest.mark.asyncio
async def test_identity_in_another_tenant_is_forbidden() -> None:
    other_tenant = UUID("22222222-2222-4222-8222-222222222222")
    user = CurrentUser(
        subject_id=SUBJECT_ID, tenant_id=TENANT_ID, username="mike", roles=frozenset({"employee"})
    )
    tenant = Tenant(id=other_tenant, slug="isolation-test", name="Isolation Test Organization")
    profile = UserProfile(
        id=UUID(SUBJECT_ID),
        tenant_id=other_tenant,
        external_subject=SUBJECT_ID,
        username="mike",
        display_name="Mike Rahman",
        department="engineering",
        is_active=True,
    )

    with pytest.raises(IdentityNotProvisionedError):
        await get_identity_profile(_session_returning((profile, tenant)), user)
