from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
SALARY = "10000000-0000-4000-8000-000000000001"
ENGINEERING = "10000000-0000-4000-8000-000000000002"
NGO = "10000000-0000-4000-8000-000000000003"
OTHER = "10000000-0000-4000-8000-000000000004"


@dataclass(frozen=True)
class Check:
    username: str
    password_env: str
    default_password: str
    resource_id: str
    expected_status: int
    tenant_id: str


CHECKS = (
    Check("mike", "KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only", SALARY, 404, DEMO_TENANT),
    Check("mike", "KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only", ENGINEERING, 200, DEMO_TENANT),
    Check("helen.hr", "KRIBU_DEMO_HR_PASSWORD", "hr_demo_only", SALARY, 200, DEMO_TENANT),
    Check("helen.hr", "KRIBU_DEMO_HR_PASSWORD", "hr_demo_only", ENGINEERING, 404, DEMO_TENANT),
    Check(
        "priya.manager", "KRIBU_DEMO_MANAGER_PASSWORD", "manager_demo_only", NGO, 200, DEMO_TENANT
    ),
    Check(
        "priya.manager",
        "KRIBU_DEMO_MANAGER_PASSWORD",
        "manager_demo_only",
        SALARY,
        404,
        DEMO_TENANT,
    ),
    Check(
        "evan.external",
        "KRIBU_DEMO_EXTERNAL_PASSWORD",
        "external_demo_only",
        OTHER,
        200,
        OTHER_TENANT,
    ),
    Check(
        "evan.external",
        "KRIBU_DEMO_EXTERNAL_PASSWORD",
        "external_demo_only",
        SALARY,
        404,
        OTHER_TENANT,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the local synthetic Guard boundary.")
    parser.add_argument("--confirm-synthetic", action="store_true")
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


async def token_for(client: httpx.AsyncClient, keycloak_url: str, check: Check) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": check.username,
            "password": os.getenv(check.password_env, check.default_password),
        },
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak did not issue a demo token.")
    return token


async def verify_audit(
    database_url: str, correlation_ids: dict[str, list[str]]
) -> dict[str, object]:
    connection = await asyncpg.connect(database_url)
    try:
        without_context = await connection.fetchval("SELECT count(*) FROM resource_descriptors")
        if without_context != 0:
            raise RuntimeError("Resource RLS exposed rows without tenant context.")

        counts: dict[str, int] = {}
        for tenant_id, ids in correlation_ids.items():
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                resource_count = await connection.fetchval(
                    "SELECT count(*) FROM resource_descriptors"
                )
                audit_count = await connection.fetchval(
                    "SELECT count(*) FROM authorization_audit_events "
                    "WHERE correlation_id = ANY($1::text[])",
                    ids,
                )
                expected_resources = 3 if tenant_id == DEMO_TENANT else 1
                if resource_count != expected_resources or audit_count != len(ids):
                    raise RuntimeError("Tenant resource or authorization audit check failed.")
                counts[tenant_id] = audit_count

        update_blocked = False
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", DEMO_TENANT)
            await connection.execute(
                "UPDATE authorization_audit_events SET reason_code = 'tampered' WHERE false"
            )
        except asyncpg.InsufficientPrivilegeError:
            update_blocked = True
        finally:
            await transaction.rollback()
        if not update_blocked:
            raise RuntimeError("The runtime role can update audit events.")
        return {
            "rows_without_tenant": without_context,
            "audit_counts": counts,
            "audit_update_blocked": update_blocked,
        }
    finally:
        await connection.close()


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to run without --confirm-synthetic.")

    outcomes: list[dict[str, object]] = []
    correlation_ids: dict[str, list[str]] = {DEMO_TENANT: [], OTHER_TENANT: []}
    async with httpx.AsyncClient(timeout=10) as client:
        anonymous = await client.get(f"{args.api_url}/demo/resources/{SALARY}")
        if anonymous.status_code != 401:
            raise RuntimeError("Anonymous access was not rejected.")

        tokens: dict[str, str] = {}
        for check in CHECKS:
            if check.username not in tokens:
                tokens[check.username] = await token_for(client, args.keycloak_url, check)
            correlation_id = f"guard-verify-{uuid4()}"
            response = await client.get(
                f"{args.api_url}/demo/resources/{check.resource_id}",
                headers={
                    "Authorization": f"Bearer {tokens[check.username]}",
                    "X-Correlation-ID": correlation_id,
                },
            )
            if response.status_code != check.expected_status:
                raise RuntimeError(
                    f"Unexpected status for {check.username} and {check.resource_id}: "
                    f"{response.status_code}"
                )
            if response.status_code == 200 and not response.json()["content"].startswith(
                "SYNTHETIC ONLY"
            ):
                raise RuntimeError("The API returned unexpected demo content.")
            correlation_ids[check.tenant_id].append(correlation_id)
            outcomes.append(
                {
                    "user": check.username,
                    "resource_id": check.resource_id,
                    "status": response.status_code,
                }
            )

        spoofed = await client.get(
            f"{args.api_url}/demo/resources/{SALARY}",
            params={"tenant_id": DEMO_TENANT, "roles": "hr_manager"},
            headers={"Authorization": f"Bearer {tokens['mike']}"},
        )
        if spoofed.status_code != 404:
            raise RuntimeError("Caller-controlled attributes changed the Guard decision.")

    audit = await verify_audit(args.database_url, correlation_ids)
    print(json.dumps({"checks": outcomes, "spoofed_mike_status": 404, "audit": audit}, indent=2))


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
