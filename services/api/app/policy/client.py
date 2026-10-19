from __future__ import annotations

import httpx
from pydantic import ValidationError

from app.policy.contracts import AuthorizationDecision, AuthorizationInput, OpaResponse
from app.policy.errors import PolicyUnavailableError


class OpaClient:
    def __init__(self, base_url: str, timeout_seconds: float, expected_version: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds, trust_env=False
        )
        self._expected_version = expected_version

    async def close(self) -> None:
        await self._client.aclose()

    async def ready(self) -> bool:
        try:
            response = await self._client.get("/v1/data/kribu/authz/policy_version")
            response.raise_for_status()
            payload = response.json()
            return isinstance(payload, dict) and payload.get("result") == self._expected_version
        except (httpx.HTTPError, ValueError):
            return False

    async def evaluate(self, policy_input: AuthorizationInput) -> AuthorizationDecision:
        try:
            response = await self._client.post(
                "/v1/data/kribu/authz/decision",
                json={"input": policy_input.model_dump(mode="json")},
            )
            response.raise_for_status()
            envelope = OpaResponse.model_validate(response.json())
            decision = envelope.result
            if decision.policy_version != self._expected_version:
                raise PolicyUnavailableError()
            return decision
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise PolicyUnavailableError() from exc
