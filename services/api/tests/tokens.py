"""Locally signed OIDC tokens for unit and integration tests (no Keycloak needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK

from app.core.config import Settings
from app.identity.tokens import OidcTokenVerifier

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
    """Build a real verifier whose JWKS lookup returns the local test key."""
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
