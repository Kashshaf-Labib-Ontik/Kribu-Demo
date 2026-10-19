from __future__ import annotations

import asyncio
import logging

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError
from pydantic import ValidationError

from app.core.config import Settings
from app.identity.contracts import AccessTokenClaims, CurrentUser
from app.identity.errors import IdentityProviderUnavailableError, InvalidAccessTokenError

logger = logging.getLogger(__name__)


class OidcTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer_url.rstrip("/")
        self._audience = settings.oidc_audience
        self._clock_skew_seconds = settings.oidc_clock_skew_seconds
        self._jwks_client = PyJWKClient(
            settings.oidc_jwks_url,
            cache_jwk_set=True,
            cache_keys=True,
            lifespan=300,
            timeout=5,
        )

    async def verify(self, encoded_token: str) -> CurrentUser:
        try:
            signing_key = await asyncio.to_thread(
                self._jwks_client.get_signing_key_from_jwt,
                encoded_token,
            )
            raw_claims = jwt.decode(
                encoded_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={"require": ["aud", "exp", "iat", "iss", "sub"]},
            )
            claims = AccessTokenClaims.model_validate(raw_claims)
        except PyJWKClientConnectionError as exc:
            logger.warning("identity provider signing keys unavailable", exc_info=True)
            raise IdentityProviderUnavailableError() from exc
        except (InvalidTokenError, PyJWKClientError, ValidationError, OSError, ValueError) as exc:
            # Log the failure class only: messages can echo claim values.
            logger.info("access token rejected: %s", type(exc).__name__)
            raise InvalidAccessTokenError() from exc

        roles = frozenset(role for role in claims.realm_access.roles if role.strip())
        if not roles:
            raise InvalidAccessTokenError()

        return CurrentUser(
            subject_id=claims.sub,
            tenant_id=claims.tenant_id,
            username=claims.preferred_username,
            roles=roles,
            department=claims.department,
        )
