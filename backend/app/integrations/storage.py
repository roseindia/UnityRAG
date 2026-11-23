"""Tenant-aware object storage (extension 13).

Keys are generated server-side as
    tenants/<tenant_id>/documents/<document_id>/<version_id>/original<ext>
Client-provided paths are never used.  Every read/write resolves the key and
verifies it stays inside the caller's tenant prefix (path traversal guard).
Only the local filesystem backend is implemented (development and on-prem
file shares).  An S3 / Azure Blob backend must implement the ObjectStorage
protocol below; it is not part of this release (see REQUIREMENTS_GAPS.md).
Encryption at rest is the storage volume's / service's responsibility (NFR-036).
"""
from __future__ import annotations

import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import PermissionDenied

_EXT = re.compile(r"^\.[a-z0-9]{1,8}$")


class ObjectStorage(Protocol):
    def put(self, tenant_id: uuid.UUID, key: str, data: bytes) -> str: ...
    def get(self, tenant_id: uuid.UUID, key: str) -> bytes: ...
    def delete(self, tenant_id: uuid.UUID, key: str) -> None: ...
    def tenant_usage_bytes(self, tenant_id: uuid.UUID) -> int: ...


def document_key(tenant_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    ext = ext if _EXT.match(ext) else ".bin"
    return f"tenants/{tenant_id}/documents/{document_id}/{version_id}/original{ext}"


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: uuid.UUID, key: str) -> Path:
        prefix = (self.root / "tenants" / str(tenant_id)).resolve()
        path = (self.root / key).resolve()
        if prefix not in path.parents:
            raise PermissionDenied("Storage key outside tenant scope", code="storage_scope_violation")
        return path

    def put(self, tenant_id: uuid.UUID, key: str, data: bytes) -> str:
        path = self._path(tenant_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return key

    def get(self, tenant_id: uuid.UUID, key: str) -> bytes:
        return self._path(tenant_id, key).read_bytes()

    def delete(self, tenant_id: uuid.UUID, key: str) -> None:
        path = self._path(tenant_id, key)
        if path.exists():
            path.unlink()

    def tenant_usage_bytes(self, tenant_id: uuid.UUID) -> int:
        base = self.root / "tenants" / str(tenant_id)
        return sum(p.stat().st_size for p in base.rglob("*") if p.is_file()) if base.exists() else 0


@lru_cache
def get_storage() -> ObjectStorage:
    return LocalStorage(get_settings().storage_root)
