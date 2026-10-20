"""Evaluate the synthetic retrieval golden set through the public API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

PASSWORDS = {
    "mike": ("KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only"),
    "helen.hr": ("KRIBU_DEMO_HR_PASSWORD", "hr_demo_only"),
    "priya.manager": ("KRIBU_DEMO_MANAGER_PASSWORD", "manager_demo_only"),
    "evan.external": ("KRIBU_DEMO_EXTERNAL_PASSWORD", "external_demo_only"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate synthetic retrieval quality and safety.")
    parser.add_argument("--confirm-synthetic", action="store_true")
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    return parser.parse_args()


async def _token(client: httpx.AsyncClient, keycloak_url: str, username: str) -> str:
    password_env, default_password = PASSWORDS[username]
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


async def _search(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    case: dict[str, Any],
) -> list[dict[str, Any]]:
    response = await client.post(
        f"{api_url}/retrieval/search",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": f"retrieval-golden-{uuid4()}",
        },
        json={
            "query": case["query"],
            "limit": 8,
            "filters": {"domain": case["domain"]},
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"Golden query failed safely with HTTP {response.status_code}.")
    evidence: list[dict[str, Any]] = response.json()["evidence"]
    if any(
        not item["source_references"]
        or not item["version_id"]
        or item["untrusted_source"] is not True
        for item in evidence
    ):
        raise RuntimeError("Retrieval returned evidence without its immutable provenance contract.")
    return evidence


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to evaluate without --confirm-synthetic.")
    golden_path = Path(__file__).resolve().parents[1] / "demo_data" / "retrieval_golden.json"
    golden: dict[str, list[dict[str, Any]]] = json.loads(golden_path.read_text("utf-8"))
    usernames = {case["username"] for cases in golden.values() for case in cases}
    reciprocal_ranks: list[float] = []
    recalled = 0
    violations: list[str] = []

    async with httpx.AsyncClient(timeout=45) as client:
        tokens = {
            username: await _token(client, args.keycloak_url, username)
            for username in sorted(usernames)
        }
        for case in golden["positive"]:
            evidence = await _search(client, args.api_url, tokens[case["username"]], case)
            titles = [item["title"] for item in evidence]
            try:
                rank = titles.index(case["expected_title"]) + 1
            except ValueError:
                rank = 0
            recalled += int(0 < rank <= 5)
            reciprocal_ranks.append(1 / rank if rank else 0.0)
        for case in golden["negative"]:
            evidence = await _search(client, args.api_url, tokens[case["username"]], case)
            if case["forbidden_title"] in {item["title"] for item in evidence}:
                violations.append(case["query"])

    recall_at_5 = recalled / len(golden["positive"])
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    if recall_at_5 < 0.90 or mean_reciprocal_rank < 0.75 or violations:
        raise RuntimeError(
            "Retrieval acceptance failed: "
            f"recall@5={recall_at_5:.3f}, mrr={mean_reciprocal_rank:.3f}, "
            f"authorization_violations={len(violations)}"
        )
    print(
        json.dumps(
            {
                "positive_queries": len(golden["positive"]),
                "authorization_negative_queries": len(golden["negative"]),
                "recall_at_5": round(recall_at_5, 3),
                "mean_reciprocal_rank": round(mean_reciprocal_rank, 3),
                "authorization_violations": len(violations),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
