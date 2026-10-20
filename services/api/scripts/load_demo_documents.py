"""Idempotently load the three fictional source packs through the public upload API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class SourceDocument:
    relative_path: str
    username: str
    password_env: str
    default_password: str
    metadata: dict[str, object]


SOURCES = (
    SourceDocument(
        "ngo/march_progress_report.md",
        "priya.manager",
        "KRIBU_DEMO_MANAGER_PASSWORD",
        "manager_demo_only",
        {
            "title": "Synthetic NGO March progress report",
            "classification": "internal",
            "department": "programs",
            "domain": "ngo",
            "project": "Community clinic",
            "document_date": "2026-03-31",
            "grants": [{"principal_type": "department", "principal_id": "programs"}],
        },
    ),
    SourceDocument(
        "ngo/april_meeting_minutes.md",
        "priya.manager",
        "KRIBU_DEMO_MANAGER_PASSWORD",
        "manager_demo_only",
        {
            "title": "Synthetic NGO April review minutes",
            "classification": "internal",
            "department": "programs",
            "domain": "ngo",
            "project": "Community clinic",
            "document_date": "2026-04-30",
            "grants": [{"principal_type": "department", "principal_id": "programs"}],
        },
    ),
    SourceDocument(
        "ngo/milestone_register.csv",
        "priya.manager",
        "KRIBU_DEMO_MANAGER_PASSWORD",
        "manager_demo_only",
        {
            "title": "Synthetic NGO milestone register",
            "classification": "internal",
            "department": "programs",
            "domain": "ngo",
            "project": "Community clinic",
            "document_date": "2026-05-31",
            "grants": [{"principal_type": "department", "principal_id": "programs"}],
        },
    ),
    SourceDocument(
        "hr/roger_albert_salary_history.md",
        "helen.hr",
        "KRIBU_DEMO_HR_PASSWORD",
        "hr_demo_only",
        {
            "title": "Synthetic Roger Albert compensation history",
            "classification": "restricted_hr",
            "department": "human-resources",
            "domain": "hr",
            "document_date": "2026-02-01",
            "grants": [{"principal_type": "role", "principal_id": "hr_manager"}],
        },
    ),
    SourceDocument(
        "hr/benefit_policy.md",
        "helen.hr",
        "KRIBU_DEMO_HR_PASSWORD",
        "hr_demo_only",
        {
            "title": "Synthetic engineering benefits policy",
            "classification": "internal",
            "department": "human-resources",
            "domain": "hr",
            "document_date": "2026-01-01",
            "grants": [{"principal_type": "department", "principal_id": "human-resources"}],
        },
    ),
    SourceDocument(
        "complaints/complaint_register.csv",
        "mike",
        "KRIBU_DEMO_MIKE_PASSWORD",
        "mike_demo_only",
        {
            "title": "Synthetic client complaint register",
            "classification": "internal",
            "department": "engineering",
            "domain": "complaints",
            "document_date": "2026-06-01",
            "grants": [{"principal_type": "department", "principal_id": "engineering"}],
        },
    ),
    SourceDocument(
        "complaints/service_notes.md",
        "mike",
        "KRIBU_DEMO_MIKE_PASSWORD",
        "mike_demo_only",
        {
            "title": "Synthetic client service notes",
            "classification": "internal",
            "department": "engineering",
            "domain": "complaints",
            "document_date": "2026-06-02",
            "grants": [{"principal_type": "department", "principal_id": "engineering"}],
        },
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load synthetic Iteration 6 demo documents.")
    parser.add_argument("--confirm-synthetic", action="store_true")
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    return parser.parse_args()


async def _token(client: httpx.AsyncClient, url: str, source: SourceDocument) -> str:
    response = await client.post(
        f"{url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": source.username,
            "password": os.getenv(source.password_env, source.default_password),
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


async def _wait_for_preview(
    client: httpx.AsyncClient, *, api_url: str, token: str, document_id: str, version_id: str
) -> int:
    """Require a complete, authorized preview for every synthetic source pack."""
    url = f"{api_url}/documents/{document_id}/versions/{version_id}/preview"
    for _ in range(45):
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 202:
            await asyncio.sleep(2)
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Preview failed for {document_id}: {response.status_code}")
        blocks = response.json()["blocks"]
        if not blocks:
            raise RuntimeError(f"Preview contains no normalized blocks for {document_id}")
        return len(blocks)
    raise RuntimeError(f"Timed out waiting for parsed preview of {document_id}")


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to load demo data without --confirm-synthetic.")
    root = Path(__file__).resolve().parents[1] / "demo_data"
    tokens: dict[str, str] = {}
    loaded: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for source in SOURCES:
            token = tokens.get(source.username)
            if token is None:
                token = await _token(client, args.keycloak_url, source)
                tokens[source.username] = token
            path = root / source.relative_path
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()[:24]
            response = await client.post(
                f"{args.api_url}/documents/uploads",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"demo-{digest}"},
                data={"metadata": json.dumps(source.metadata)},
                files={"file": (path.name, content, "text/plain")},
            )
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"Failed to load {source.relative_path}: {response.status_code}")
            document_id = str(response.json()["document_id"])
            version_id = str(response.json()["version"]["id"])
            block_count = await _wait_for_preview(
                client,
                api_url=args.api_url,
                token=token,
                document_id=document_id,
                version_id=version_id,
            )
            loaded.append(
                {
                    "source": source.relative_path,
                    "document_id": document_id,
                    "status": response.status_code,
                    "preview_blocks": block_count,
                }
            )
    print(json.dumps({"loaded": loaded}, indent=2))


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
