"""Live synthetic verification for authorized hybrid retrieval and exact evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import uuid4

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify synthetic authorized retrieval.")
    parser.add_argument("--confirm-synthetic", action="store_true")
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    return parser.parse_args()


async def token_for(
    client: httpx.AsyncClient,
    keycloak_url: str,
    username: str,
    password_env: str,
    default_password: str,
) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": username,
            "password": os.getenv(password_env, default_password),
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


async def search(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    query: str,
    *,
    domain: str | None = None,
    project: str | None = None,
) -> httpx.Response:
    body: dict[str, object] = {"query": query, "limit": 8}
    filters: dict[str, str] = {}
    if domain is not None:
        filters["domain"] = domain
    if project is not None:
        filters["project"] = project
    if filters:
        body["filters"] = filters
    return await client.post(
        f"{api_url}/retrieval/search",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": f"retrieval-live-{uuid4()}",
        },
        json=body,
    )


async def wait_for_evidence(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    query: str,
    *,
    domain: str,
    title_fragment: str,
    project: str | None = None,
) -> dict[str, object]:
    for _ in range(60):
        response = await search(client, api_url, token, query, domain=domain, project=project)
        if response.status_code != 200:
            raise RuntimeError(f"Retrieval failed: {response.status_code} {response.text}")
        payload = response.json()
        evidence = payload["evidence"]
        if any(title_fragment.lower() in item["title"].lower() for item in evidence):
            return payload
        await asyncio.sleep(2)
    raise RuntimeError(f"Timed out waiting for an index containing {title_fragment!r}.")


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to run without --confirm-synthetic.")
    async with httpx.AsyncClient(timeout=45) as client:
        priya, helen, mike, evan = await asyncio.gather(
            token_for(
                client,
                args.keycloak_url,
                "priya.manager",
                "KRIBU_DEMO_MANAGER_PASSWORD",
                "manager_demo_only",
            ),
            token_for(
                client,
                args.keycloak_url,
                "helen.hr",
                "KRIBU_DEMO_HR_PASSWORD",
                "hr_demo_only",
            ),
            token_for(
                client,
                args.keycloak_url,
                "mike",
                "KRIBU_DEMO_MIKE_PASSWORD",
                "mike_demo_only",
            ),
            token_for(
                client,
                args.keycloak_url,
                "evan.external",
                "KRIBU_DEMO_EXTERNAL_PASSWORD",
                "external_demo_only",
            ),
        )
        ngo = await wait_for_evidence(
            client,
            args.api_url,
            priya,
            "Why is the community clinic project behind schedule?",
            domain="ngo",
            title_fragment="progress report",
            project="Community Clinic",
        )
        hr = await wait_for_evidence(
            client,
            args.api_url,
            helen,
            "What is Roger Albert's compensation?",
            domain="hr",
            title_fragment="compensation history",
        )
        salary_documents = {item["document_id"] for item in hr["evidence"]}
        mike_salary = await search(
            client,
            args.api_url,
            mike,
            "How much does Roger Albert earn?",
            domain="hr",
        )
        evan_ngo = await search(
            client,
            args.api_url,
            evan,
            "Why is the community clinic project delayed?",
            domain="ngo",
        )
        if mike_salary.status_code != 200 or evan_ngo.status_code != 200:
            raise RuntimeError("Negative retrieval verification did not return a safe response.")
        if salary_documents & {item["document_id"] for item in mike_salary.json()["evidence"]}:
            raise RuntimeError("Restricted salary evidence leaked to Mike.")
        ngo_documents = {item["document_id"] for item in ngo["evidence"]}
        if ngo_documents & {item["document_id"] for item in evan_ngo.json()["evidence"]}:
            raise RuntimeError("NGO evidence crossed the tenant boundary.")
        if any(not item["source_references"] for item in ngo["evidence"] + hr["evidence"]):
            raise RuntimeError("Evidence without exact source provenance was returned.")
    print(
        json.dumps(
            {
                "ngo_evidence": len(ngo["evidence"]),
                "hr_evidence": len(hr["evidence"]),
                "mike_salary_leakage": 0,
                "cross_tenant_leakage": 0,
                "index_contract": ngo["index_contract"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
