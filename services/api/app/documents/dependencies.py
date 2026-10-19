from typing import cast

from fastapi import Request

from app.documents.storage import ObjectStore


def get_object_store(request: Request) -> ObjectStore:
    return cast(ObjectStore, request.app.state.object_store)
