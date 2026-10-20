"""Live synthetic verification for the Iteration 5 document lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class DemoUser:
    username: str
    password_env: str
    default_password: str


USERS = (
    DemoUser("helen.hr", "KRIBU_DEMO_HR_PASSWORD", "hr_demo_only"),
    DemoUser("mike", "KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only"),
    DemoUser("evan.external", "KRIBU_DEMO_EXTERNAL_PASSWORD", "external_demo_only"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the synthetic document lifecycle.")
    parser.add_argument("--confirm-synthetic", action="store_true")
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    return parser.parse_args()


async def token_for(client: httpx.AsyncClient, keycloak_url: str, user: DemoUser) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": user.username,
            "password": os.getenv(user.password_env, user.default_password),
        },
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Keycloak did not issue a token for {user.username}.")
    return token


def bearer(token: str, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def upload_payload(content: bytes) -> dict[str, object]:
    metadata = {
        "title": "Synthetic HR document lifecycle verification",
        "classification": "restricted_hr",
        "department": "human-resources",
        "domain": "hr",
        "document_date": "2026-10-20",
        "grants": [{"principal_type": "role", "principal_id": "hr_manager"}],
    }
    return {
        "data": {"metadata": json.dumps(metadata)},
        "files": {"file": ("synthetic-hr.pdf", content, "application/pdf")},
    }


async def expect_status(response: httpx.Response, expected: int, operation: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{operation} returned {response.status_code}; expected {expected}: {response.text}"
        )


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to run without --confirm-synthetic.")

    first_bytes = f"%PDF-1.4\n% SYNTHETIC ONLY: v1 {uuid4()}\n%%EOF\n".encode()
    second_bytes = f"%PDF-1.4\n% SYNTHETIC ONLY: v2 {uuid4()}\n%%EOF\n".encode()
    create_key = f"document-verify-{uuid4()}"
    version_key = f"document-version-verify-{uuid4()}"

    async with httpx.AsyncClient(timeout=15) as client:
        tokens = {user.username: await token_for(client, args.keycloak_url, user) for user in USERS}

        anonymous = await client.post(
            f"{args.api_url}/documents/uploads", **upload_payload(first_bytes)
        )
        await expect_status(anonymous, 401, "anonymous upload")

        first = await client.post(
            f"{args.api_url}/documents/uploads",
            headers=bearer(tokens["helen.hr"], key=create_key),
            **upload_payload(first_bytes),
        )
        await expect_status(first, 201, "document create")
        replay = await client.post(
            f"{args.api_url}/documents/uploads",
            headers=bearer(tokens["helen.hr"], key=create_key),
            **upload_payload(first_bytes),
        )
        await expect_status(replay, 201, "document create replay")
        if replay.json() != first.json():
            raise RuntimeError("Create idempotency replay changed the stored response.")

        document_id = first.json()["document_id"]
        reads: dict[str, int] = {}
        for username in ("helen.hr", "mike", "evan.external"):
            response = await client.get(
                f"{args.api_url}/documents/{document_id}",
                headers=bearer(tokens[username]),
            )
            reads[username] = response.status_code
        if reads != {"helen.hr": 200, "mike": 404, "evan.external": 404}:
            raise RuntimeError(f"Unexpected document authorization results: {reads}")

        version_payload = {
            "files": {"file": ("synthetic-hr-v2.pdf", second_bytes, "application/pdf")}
        }
        version = await client.post(
            f"{args.api_url}/documents/{document_id}/versions",
            headers=bearer(tokens["helen.hr"], key=version_key),
            **version_payload,
        )
        await expect_status(version, 201, "version create")
        version_replay = await client.post(
            f"{args.api_url}/documents/{document_id}/versions",
            headers=bearer(tokens["helen.hr"], key=version_key),
            **version_payload,
        )
        await expect_status(version_replay, 201, "version replay")
        if version_replay.json() != version.json():
            raise RuntimeError("Version idempotency replay changed the stored response.")

        same_latest = await client.post(
            f"{args.api_url}/documents/{document_id}/versions",
            headers=bearer(tokens["helen.hr"], key=f"same-latest-{uuid4()}"),
            **version_payload,
        )
        await expect_status(same_latest, 200, "same-as-latest version")

        final = await client.get(
            f"{args.api_url}/documents/{document_id}",
            headers=bearer(tokens["helen.hr"]),
        )
        await expect_status(final, 200, "final document read")
        version_numbers = [item["version_number"] for item in final.json()["versions"]]
        if version_numbers != [1, 2]:
            raise RuntimeError(f"Unexpected stored versions: {version_numbers}")

    print(
        json.dumps(
            {
                "document_id": document_id,
                "anonymous_upload": 401,
                "create_and_replay": [201, 201],
                "read_statuses": reads,
                "version_and_replay": [201, 201],
                "same_as_latest": 200,
                "versions": [1, 2],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
