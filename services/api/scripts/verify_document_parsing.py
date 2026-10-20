"""Live synthetic verification for asynchronous parsing, preview provenance, and safe denial."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import uuid4

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the synthetic parsing lifecycle.")
    parser.add_argument("--confirm-synthetic", action="store_true")
    parser.add_argument("--keycloak-url", default="http://localhost:8180")
    parser.add_argument("--api-url", default="http://localhost:8000/v1")
    return parser.parse_args()


async def token_for(
    client: httpx.AsyncClient, keycloak_url: str, username: str, password: str
) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/kribu-demo/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "kribu-verifier",
            "username": username,
            "password": password,
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


async def wait_for_preview(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> httpx.Response:
    for _ in range(45):
        response = await client.get(url, headers=headers)
        if response.status_code != 202:
            return response
        await asyncio.sleep(2)
    raise RuntimeError("Timed out waiting for the single-worker parser.")


async def run(args: argparse.Namespace) -> None:
    if not args.confirm_synthetic:
        raise SystemExit("Refusing to run without --confirm-synthetic.")
    metadata = {
        "title": "Synthetic parsing verification",
        "classification": "internal",
        "department": "engineering",
        "domain": "complaints",
        "grants": [{"principal_type": "department", "principal_id": "engineering"}],
    }
    run_marker = str(uuid4())
    first = f"# Synthetic source\nInvoice delay is recurring.\nRun: {run_marker}\n".encode()
    second = (
        "# Synthetic source\n"
        "Invoice delay is recurring.\n"
        "Three cases reopened.\n"
        f"Run: {run_marker}\n"
    ).encode()
    async with httpx.AsyncClient(timeout=30) as client:
        mike = await token_for(
            client,
            args.keycloak_url,
            "mike",
            os.getenv("KRIBU_DEMO_MIKE_PASSWORD", "mike_demo_only"),
        )
        evan = await token_for(
            client,
            args.keycloak_url,
            "evan.external",
            os.getenv("KRIBU_DEMO_EXTERNAL_PASSWORD", "external_demo_only"),
        )
        create_key = f"parse-create-{uuid4()}"
        payload = {
            "data": {"metadata": json.dumps(metadata)},
            "files": {"file": ("synthetic-complaints.md", first, "text/markdown")},
        }
        created = await client.post(
            f"{args.api_url}/documents/uploads",
            headers={"Authorization": f"Bearer {mike}", "Idempotency-Key": create_key},
            **payload,
        )
        if created.status_code != 201:
            raise RuntimeError(f"Upload failed: {created.status_code} {created.text}")
        replay = await client.post(
            f"{args.api_url}/documents/uploads",
            headers={"Authorization": f"Bearer {mike}", "Idempotency-Key": create_key},
            **payload,
        )
        if replay.status_code != 201 or replay.json() != created.json():
            raise RuntimeError("Upload idempotency replay changed the response.")
        document_id = created.json()["document_id"]
        version = await client.post(
            f"{args.api_url}/documents/{document_id}/versions",
            headers={
                "Authorization": f"Bearer {mike}",
                "Idempotency-Key": f"parse-version-{uuid4()}",
            },
            files={"file": ("synthetic-complaints-v2.md", second, "text/markdown")},
        )
        if version.status_code != 201:
            raise RuntimeError(f"Version upload failed: {version.status_code} {version.text}")
        version_id = version.json()["version"]["id"]
        preview_url = f"{args.api_url}/documents/{document_id}/versions/{version_id}/preview"
        preview = await wait_for_preview(client, preview_url, {"Authorization": f"Bearer {mike}"})
        if preview.status_code != 200 or preview.json()["blocks"][-1]["locator"]["line"] != 4:
            raise RuntimeError(f"Unexpected preview: {preview.status_code} {preview.text}")
        download = await client.get(
            f"{args.api_url}/documents/{document_id}/versions/{version_id}/download",
            headers={"Authorization": f"Bearer {mike}"},
        )
        denied = await client.get(preview_url, headers={"Authorization": f"Bearer {evan}"})
        if download.content != second or denied.status_code != 404:
            raise RuntimeError("Download integrity or cross-tenant denial failed.")
    print(
        json.dumps(
            {
                "document_id": document_id,
                "preview_blocks": len(preview.json()["blocks"]),
                "download_bytes": len(download.content),
                "cross_tenant_preview": denied.status_code,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
