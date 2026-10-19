from typing import cast

from fastapi import Request

from app.policy.client import OpaClient


def get_opa_client(request: Request) -> OpaClient:
    return cast(OpaClient, request.app.state.opa_client)
