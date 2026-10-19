from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx

DEMO_TENANT_ID = "11111111-1111-4111-8111-111111111111"
ISOLATION_TENANT_ID = "22222222-2222-4222-8222-222222222222"


@dataclass(frozen=True)
class DemoUser:
    username: str
    password_environment_variable: str
    default_password: str
    expected_tenant_id: str


USERS = (
    DemoUser("mike", "KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only", DEMO_TENANT_ID),
    DemoUser(
        "evan.external",
        "KRIBU_DEMO_EXTERNAL_PASSWORD",
        "external_demo_only",
        ISOLATION_TENANT_ID,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify local OIDC and tenant isolation.")
    parser.add_argument(
        "--confirm-synthetic",
        action="store_true",
        help="Confirm that only the built-in synthetic identities are used.",
    )
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "KRIBU_APP_DATABASE_URL",
            "postgresql://kribu_app:kribu_app_dev_only@localhost:5432/kribu",
        ),
    )
    return parser.parse_args()


async def obtain_access_token(
    client: httpx.AsyncClient,
    *,
    keycloak_url: str,
    user: DemoUser,
) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": user.username,
            "password": os.getenv(
                user.password_environment_variable,
                user.default_password,
            ),
        },
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak did not return an access token.")
    return token


async def verify_api_identity(
    client: httpx.AsyncClient,
    *,
    api_url: str,
    token: str,
    user: DemoUser,
) -> dict[str, object]:
    response = await client.get(
        f"{api_url}/identity/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("username") != user.username:
        raise RuntimeError("The API returned the wrong demo identity.")
    if payload.get("tenant_id") != user.expected_tenant_id:
        raise RuntimeError("The API returned the wrong tenant context.")
    return {
        "username": payload["username"],
        "tenant_id": payload["tenant_id"],
        "roles": payload["roles"],
    }


async def verify_rls(database_url: str) -> dict[str, object]:
    connection = await asyncpg.connect(database_url)
    try:
        without_context = await connection.fetchval("SELECT count(*) FROM tenants")

        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)",
                DEMO_TENANT_ID,
            )
            demo_rows = await connection.fetch("SELECT id::text FROM tenants ORDER BY id::text")

        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)",
                ISOLATION_TENANT_ID,
            )
            isolation_rows = await connection.fetch(
                "SELECT id::text FROM tenants ORDER BY id::text"
            )

        insert_blocked = False
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)",
                DEMO_TENANT_ID,
            )
            await connection.execute(
                """
                INSERT INTO user_profiles (
                    id, tenant_id, external_subject, username, display_name, is_active
                ) VALUES ($1, $2, $3, $4, $5, true)
                """,
                uuid4(),
                ISOLATION_TENANT_ID,
                f"rls-probe-{uuid4()}",
                f"rls-probe-{uuid4()}",
                "RLS Probe",
            )
        except asyncpg.InsufficientPrivilegeError:
            insert_blocked = True
        finally:
            await transaction.rollback()

        demo_ids = [row["id"] for row in demo_rows]
        isolation_ids = [row["id"] for row in isolation_rows]
        if without_context != 0:
            raise RuntimeError("RLS exposed tenant rows without a tenant context.")
        if demo_ids != [DEMO_TENANT_ID] or isolation_ids != [ISOLATION_TENANT_ID]:
            raise RuntimeError("RLS did not isolate tenant rows.")
        if not insert_blocked:
            raise RuntimeError("RLS allowed a cross-tenant insert.")

        return {
            "rows_without_context": without_context,
            "demo_context_rows": demo_ids,
            "isolation_context_rows": isolation_ids,
            "cross_tenant_insert_blocked": insert_blocked,
        }
    finally:
        await connection.close()


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to run without --confirm-synthetic.")

    async with httpx.AsyncClient(timeout=10) as client:
        unauthenticated = await client.get(f"{args.api_url}/identity/me")
        if unauthenticated.status_code != 401:
            raise RuntimeError("The protected endpoint did not reject an anonymous request.")

        identities = []
        for user in USERS:
            token = await obtain_access_token(client, keycloak_url=args.keycloak_url, user=user)
            identities.append(
                await verify_api_identity(
                    client,
                    api_url=args.api_url,
                    token=token,
                    user=user,
                )
            )

    rls = await verify_rls(args.database_url)
    print(json.dumps({"authentication": identities, "rls": rls}, indent=2))


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
