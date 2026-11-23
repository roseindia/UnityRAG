"""Documents, versions, collections and access management (spec 6.3, 6.16,
FR-018, FR-039, FR-040, FR-045, FR-050..FR-052, FR-109, FR-110, FR-182..FR-185,
FR-249..FR-256, extension 7.5, 7.6).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, PermissionDenied, QuotaExceeded, ValidationFailed
from app.database.session import SecurityContext
from app.integrations.storage import document_key, get_storage
from app.rag.parsers.base import MIME, UnsupportedFormat, detect_format
from app.services import quota_service
from app.services.audit import tenant_audit
from app.utils.cache import get_cache

log = logging.getLogger("app.documents")

DOCUMENT_TYPES = {"policy_wording", "policy_schedule", "endorsement", "claims_manual", "underwriting_guideline",
                  "product_brochure", "regulatory_circular", "sop", "customer_communication", "authority_matrix",
                  "faq", "other"}
CLASSIFICATIONS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
LINES = {"motor", "home", "health", "life", "travel", "marine", "liability", "property", "cyber", "workers_comp",
         "group", "general"}


def _audit(db: Session, sec: SecurityContext, category: str, event: str, rtype: str, rid: Any,
           detail: dict | None = None, outcome: str = "success") -> None:
    tenant_audit(db, tenant_id=sec.tenant_id, category=category, event_type=event, outcome=outcome,  # type: ignore[arg-type]
                 actor_user_id=sec.user_id, actor_account_id=sec.account_id, resource_type=rtype, resource_id=rid,
                 detail=detail)


def invalidate_tenant_cache(tenant_id: uuid.UUID) -> None:
    try:
        get_cache().delete_prefix(f"rag:{tenant_id}:")
    except Exception as exc:  # the epoch bump in the database already makes cached entries unreachable
        log.warning("cache invalidation failed: %s", type(exc).__name__)


def validate_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Controlled-vocabulary validation (FR-037, FR-255)."""
    errors = []
    if meta.get("document_type") and meta["document_type"] not in DOCUMENT_TYPES:
        errors.append({"field": "document_type", "message": f"must be one of {sorted(DOCUMENT_TYPES)}"})
    if meta.get("classification") and meta["classification"] not in CLASSIFICATIONS:
        errors.append({"field": "classification", "message": f"must be one of {sorted(CLASSIFICATIONS)}"})
    if meta.get("insurance_line") and meta["insurance_line"] not in LINES:
        errors.append({"field": "insurance_line", "message": f"must be one of {sorted(LINES)}"})
    ef, et = meta.get("effective_from"), meta.get("effective_to")
    if ef and et and et < ef:
        errors.append({"field": "effective_to", "message": "must not be before effective_from"})
    for j in meta.get("jurisdictions") or []:
        if not isinstance(j, str) or not (2 <= len(j) <= 10):
            errors.append({"field": "jurisdictions", "message": f"invalid jurisdiction code {j!r}"})
    if errors:
        raise ValidationFailed("Invalid document metadata", details=errors)
    return meta


def can_write_collection(db: Session, collection_id: uuid.UUID, principals: tuple[uuid.UUID, ...],
                         tenant_id: uuid.UUID) -> bool:
    return bool(db.execute(text("""SELECT 1 FROM content.collection_access
                                    WHERE collection_id = :c AND effect = 'allow' AND permission IN ('write', 'manage')
                                      AND COALESCE(principal_id, :t) = ANY (:p)"""),
                           {"c": collection_id, "t": tenant_id, "p": list(principals)}).first())


def upload(db: Session, sec: SecurityContext, *, collection_id: uuid.UUID, filename: str, data: bytes,
           metadata: dict[str, Any], document_id: uuid.UUID | None = None, admin: bool = False) -> dict[str, Any]:
    tenant_id = sec.tenant_id
    assert tenant_id
    if not data:
        raise ValidationFailed("Empty file")
    max_size = quota_service.check_limit(db, tenant_id, "max_document_size_bytes")
    if len(data) > max_size:
        raise QuotaExceeded(f"File exceeds the maximum document size of {max_size} bytes",
                            details=[{"metric": "max_document_size_bytes", "limit": max_size, "requested": len(data)}])
    try:
        fmt = detect_format(data, filename)  # content signature check before storing (FR-028, FR-030)
    except UnsupportedFormat as exc:
        raise ValidationFailed(f"File rejected: {exc}", code="unsupported_file_type") from exc
    validate_metadata(metadata)
    if not admin and not can_write_collection(db, collection_id, sec.principals, tenant_id):
        raise PermissionDenied("You may not upload to this collection")
    coll = db.execute(text("SELECT collection_id, classification, line_of_business, jurisdictions, status "
                           "FROM content.collections WHERE collection_id = :c"), {"c": collection_id}).mappings().first()
    if coll is None or coll["status"] != "active":
        raise NotFound("Collection not found")
    checksum = hashlib.sha256(data).hexdigest()

    if document_id is None:
        dup = db.execute(text("SELECT document_id FROM content.documents WHERE checksum_sha256 = :h AND deleted_at IS NULL"),
                         {"h": checksum}).scalar()
        if dup:
            raise Conflict("An identical document already exists", details=[{"document_id": str(dup)}],
                           code="duplicate_document")
        quota_service.consume(db, sec, "documents")
        document_id = uuid.uuid4()
        classification = metadata.get("classification") or coll["classification"]
        db.execute(text("""INSERT INTO content.documents (tenant_id, document_id, collection_id, title, document_type,
                                  insurance_line, product, jurisdictions, language, classification, classification_rank,
                                  lifecycle_state, owner_user_id, department_id, checksum_sha256, size_bytes, mime_type,
                                  effective_from, effective_to, review_due_at, created_by, source_ref)
                           VALUES (:t, :d, :c, :title, :dt, :lob, :prod, :jur, :lang, :cls, :rank, 'processing', :owner,
                                   :dep, :h, :size, :mime, :ef, :et, :rev, :by, :src)"""),
                   {"t": tenant_id, "d": document_id, "c": collection_id,
                    "title": (metadata.get("title") or filename.rsplit(".", 1)[0])[:300],
                    "dt": metadata.get("document_type") or "other",
                    "lob": metadata.get("insurance_line") or coll["line_of_business"],
                    "prod": metadata.get("product"), "jur": metadata.get("jurisdictions") or coll["jurisdictions"] or [],
                    "lang": metadata.get("language") or "english", "cls": classification,
                    "rank": CLASSIFICATIONS[classification], "owner": sec.user_id,
                    "dep": metadata.get("department_id"), "h": checksum, "size": len(data), "mime": MIME[fmt],
                    "ef": metadata.get("effective_from"), "et": metadata.get("effective_to"),
                    "rev": metadata.get("review_due_at"), "by": sec.user_id, "src": metadata.get("source_ref")})
        seq = 1
        event = "document_uploaded"
    else:
        doc = db.execute(text("SELECT * FROM content.documents WHERE document_id = :d FOR UPDATE"), {"d": document_id}).mappings().first()
        if doc is None:
            raise NotFound("Document not found")
        if not admin and doc["owner_user_id"] != sec.user_id and doc["created_by"] != sec.user_id:
            raise PermissionDenied("Only the document owner or an administrator may add versions")
        if db.execute(text("SELECT 1 FROM content.document_versions WHERE document_id = :d AND checksum_sha256 = :h"),
                      {"d": document_id, "h": checksum}).first():
            raise Conflict("This version is identical to an existing version", code="duplicate_version")
        seq = int(db.execute(text("SELECT COALESCE(max(version_seq), 0) + 1 FROM content.document_versions WHERE document_id = :d"),
                             {"d": document_id}).scalar_one())
        db.execute(text("UPDATE content.documents SET checksum_sha256 = :h, size_bytes = size_bytes + :s, mime_type = :m "
                        "WHERE document_id = :d"), {"h": checksum, "s": len(data), "m": MIME[fmt], "d": document_id})
        event = "document_version_uploaded"
    quota_service.consume(db, sec, "storage_bytes", len(data))
    version_id = uuid.uuid4()
    key = document_key(tenant_id, document_id, version_id, filename)
    db.execute(text("""INSERT INTO content.document_versions (tenant_id, version_id, document_id, version_seq, version_label,
                              original_filename, storage_uri, checksum_sha256, size_bytes, mime_type, detected_format,
                              effective_from, effective_to, created_by)
                       VALUES (:t, :v, :d, :seq, :label, :fn, :uri, :h, :size, :mime, :fmt, :ef, :et, :by)"""),
               {"t": tenant_id, "v": version_id, "d": document_id, "seq": seq,
                "label": metadata.get("version_label") or f"v{seq}", "fn": filename[:255], "uri": key, "h": checksum,
                "size": len(data), "mime": MIME[fmt], "fmt": fmt, "ef": metadata.get("effective_from"),
                "et": metadata.get("effective_to"), "by": sec.user_id})
    for k, v in (metadata.get("extra") or {}).items():
        db.execute(text("""INSERT INTO content.document_metadata (tenant_id, version_id, key, value, source, validated)
                           VALUES (:t, :v, :k, :val, 'user', true) ON CONFLICT DO NOTHING"""),
                   {"t": tenant_id, "v": version_id, "k": k, "val": str(v)[:500]})
    job_id = create_job(db, sec, document_id=document_id, version_id=version_id, job_type="ingest")
    get_storage().put(tenant_id, key, data)
    _audit(db, sec, "document_update", event, "document", document_id,
           {"version_id": str(version_id), "checksum": checksum, "size": len(data), "format": fmt, "job_id": str(job_id)})
    return {"document_id": document_id, "version_id": version_id, "job_id": job_id, "version_seq": seq,
            "checksum_sha256": checksum, "format": fmt, "status": "queued"}


def create_job(db: Session, sec: SecurityContext, *, document_id: uuid.UUID | None, version_id: uuid.UUID | None,
               job_type: str, priority: int = 5) -> uuid.UUID:
    quota_service.consume(db, sec, "ingestion_jobs")
    job_id = uuid.uuid4()
    key = f"{job_type}:{version_id or document_id}:{uuid.uuid4().hex[:8] if job_type != 'ingest' else 'initial'}"
    from app.core.context import get_correlation_id

    db.execute(text("""INSERT INTO ingest.ingestion_jobs (tenant_id, job_id, document_id, version_id, job_type, priority,
                              idempotency_key, initiated_by, correlation_id)
                       VALUES (:t, :j, :d, :v, :jt, :p, :k, :by, :cid)"""),
               {"t": sec.tenant_id, "j": job_id, "d": document_id, "v": version_id, "jt": job_type, "p": priority,
                "k": key, "by": sec.user_id, "cid": get_correlation_id()})
    return job_id


_DOC_COLS = """d.document_id, d.collection_id, d.title, d.document_type, d.insurance_line, d.product, d.jurisdictions,
               d.language, d.classification, d.lifecycle_state, d.owner_user_id, d.current_version_id, d.legal_hold,
               d.size_bytes, d.mime_type, d.effective_from, d.effective_to, d.review_due_at, d.created_at, d.updated_at,
               d.classification_confidence, d.duplicate_of"""


def list_documents(db: Session, *, q: str | None = None, collection_id: uuid.UUID | None = None,
                   lifecycle_state: str | None = None, document_type: str | None = None, insurance_line: str | None = None,
                   limit: int = 50, offset: int = 0, sort: str = "updated_at") -> tuple[list[dict[str, Any]], int]:
    where, params = ["d.deleted_at IS NULL"], {"limit": limit, "offset": offset}
    for col, val in (("collection_id", collection_id), ("lifecycle_state", lifecycle_state),
                     ("document_type", document_type), ("insurance_line", insurance_line)):
        if val:
            where.append(f"d.{col} = :{col}")
            params[col] = val
    if q:
        where.append("d.title ILIKE :q")
        params["q"] = f"%{q}%"
    order = {"updated_at": "d.updated_at DESC", "title": "d.title", "created_at": "d.created_at DESC",
             "size": "d.size_bytes DESC"}.get(sort, "d.updated_at DESC")
    w = " AND ".join(where)
    total = db.execute(text(f"SELECT count(*) FROM content.documents d WHERE {w}"), params).scalar_one()
    rows = db.execute(text(f"SELECT {_DOC_COLS} FROM content.documents d WHERE {w} ORDER BY {order} LIMIT :limit OFFSET :offset"),
                      params).mappings().all()
    return [dict(r) for r in rows], int(total)


def get_document(db: Session, document_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text(f"SELECT {_DOC_COLS} FROM content.documents d WHERE d.document_id = :d AND d.deleted_at IS NULL"),
                     {"d": document_id}).mappings().first()
    if row is None:
        raise NotFound("Document not found")
    doc = dict(row)
    doc["versions"] = [dict(v) for v in db.execute(text(
        """SELECT version_id, version_seq, version_label, original_filename, state, size_bytes, mime_type, page_count,
                  effective_from, effective_to, supersedes_version_id, created_at, published_at, ocr_applied, parser,
                  embedding_model FROM content.document_versions WHERE document_id = :d ORDER BY version_seq DESC"""),
        {"d": document_id}).mappings().all()]
    if doc["current_version_id"]:
        doc["metadata"] = [dict(m) for m in db.execute(text(
            "SELECT key, value, source, confidence, validated FROM content.document_metadata WHERE version_id = :v ORDER BY key"),
            {"v": doc["current_version_id"]}).mappings().all()]
    else:
        doc["metadata"] = []
    return doc


def update_metadata(db: Session, sec: SecurityContext, document_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    validate_metadata(changes)
    allowed = {k: v for k, v in changes.items() if k in {"title", "document_type", "insurance_line", "product", "jurisdictions",
                                                          "classification", "effective_from", "effective_to",
                                                          "review_due_at", "language", "owner_user_id",
                                                          "legally_privileged"} and v is not None}
    if not allowed:
        return get_document(db, document_id)
    if "classification" in allowed:
        allowed["classification_rank"] = CLASSIFICATIONS[allowed["classification"]]
    sets = ", ".join(f"{k} = :{k}" for k in allowed)
    res = db.execute(text(f"UPDATE content.documents SET {sets} WHERE document_id = :doc AND deleted_at IS NULL"),
                     {**allowed, "doc": document_id})
    if res.rowcount == 0:
        raise NotFound("Document not found")
    _refresh_acl(db, sec, document_id)
    _audit(db, sec, "document_update", "metadata_updated", "document", document_id, {"changed": sorted(allowed)})
    return get_document(db, document_id)


def _refresh_acl(db: Session, sec: SecurityContext, document_id: uuid.UUID) -> None:
    db.execute(text("SELECT app.refresh_document_acl(:d)"), {"d": document_id})
    invalidate_tenant_cache(sec.tenant_id)  # type: ignore[arg-type]


def set_lifecycle(db: Session, sec: SecurityContext, document_id: uuid.UUID, state: str, reason: str | None) -> dict[str, Any]:
    if state not in ("published", "archived", "withdrawn", "expired", "in_review", "approved"):
        raise ValidationFailed("Unsupported lifecycle state")
    doc = db.execute(text("SELECT lifecycle_state, current_version_id FROM content.documents WHERE document_id = :d FOR UPDATE"),
                     {"d": document_id}).mappings().first()
    if doc is None:
        raise NotFound("Document not found")
    if state == "published":
        pending = db.execute(text("""SELECT version_id FROM content.document_versions WHERE document_id = :d AND state = 'indexed'
                                     ORDER BY version_seq DESC LIMIT 1"""), {"d": document_id}).scalar()
        if pending:
            if doc["current_version_id"]:
                db.execute(text("UPDATE content.document_versions SET state = 'superseded' WHERE version_id = :v"),
                           {"v": doc["current_version_id"]})
            db.execute(text("UPDATE content.document_versions SET state = 'published', published_at = now() WHERE version_id = :v"),
                       {"v": pending})
            db.execute(text("UPDATE content.documents SET current_version_id = :v WHERE document_id = :d"),
                       {"v": pending, "d": document_id})
        elif not doc["current_version_id"]:
            raise Conflict("No indexed version to publish")
    db.execute(text("UPDATE content.documents SET lifecycle_state = :s WHERE document_id = :d"), {"s": state, "d": document_id})
    _refresh_acl(db, sec, document_id)
    _audit(db, sec, "document_update", "lifecycle_changed", "document", document_id,
           {"from": doc["lifecycle_state"], "to": state, "reason": reason})
    return get_document(db, document_id)


def delete_document(db: Session, sec: SecurityContext, document_id: uuid.UUID, reason: str | None) -> uuid.UUID:
    """Two-step deletion (spec 10.1): withdraw now (not retrievable), purge async."""
    doc = db.execute(text("SELECT legal_hold, lifecycle_state FROM content.documents WHERE document_id = :d FOR UPDATE"),
                     {"d": document_id}).mappings().first()
    if doc is None:
        raise NotFound("Document not found")
    if doc["legal_hold"]:
        _audit(db, sec, "document_deletion", "deletion_blocked_legal_hold", "document", document_id, outcome="denied")
        raise Conflict("Document is under legal hold and cannot be deleted", code="legal_hold")
    db.execute(text("UPDATE content.documents SET lifecycle_state = 'withdrawn', deleted_at = now() WHERE document_id = :d"),
               {"d": document_id})
    _refresh_acl(db, sec, document_id)
    job_id = create_job(db, sec, document_id=document_id, version_id=None, job_type="delete", priority=2)
    _audit(db, sec, "document_deletion", "deletion_requested", "document", document_id,
           {"job_id": str(job_id), "reason": reason})
    return job_id


def set_legal_hold(db: Session, sec: SecurityContext, document_id: uuid.UUID, hold: bool, reason: str) -> None:
    res = db.execute(text("UPDATE content.documents SET legal_hold = :h WHERE document_id = :d"), {"h": hold, "d": document_id})
    if res.rowcount == 0:
        raise NotFound("Document not found")
    _audit(db, sec, "administration", "legal_hold_placed" if hold else "legal_hold_released", "document", document_id,
           {"reason": reason})


def read_original(db: Session, sec: SecurityContext, document_id: uuid.UUID,
                  version_id: uuid.UUID | None = None) -> tuple[bytes, str, str]:
    """Access verified at request time through RLS on documents/versions (FR-110)."""
    row = db.execute(text("""SELECT v.storage_uri, v.original_filename, v.mime_type FROM content.document_versions v
                              JOIN content.documents d ON d.document_id = v.document_id
                             WHERE v.document_id = :d AND v.version_id = COALESCE(:v, d.current_version_id)
                               AND d.deleted_at IS NULL"""), {"d": document_id, "v": version_id}).mappings().first()
    if row is None:
        _audit(db, sec, "document_access", "download_denied", "document", document_id, outcome="denied")
        raise NotFound("Document not found")
    data = get_storage().get(sec.tenant_id, row["storage_uri"])  # type: ignore[arg-type]
    _audit(db, sec, "document_access", "download", "document", document_id, {"version_id": str(version_id) if version_id else None})
    return data, row["original_filename"], row["mime_type"]


def preview(db: Session, sec: SecurityContext, document_id: uuid.UUID, page: int | None, chunk_id: uuid.UUID | None) -> dict[str, Any]:
    from app.rag.citations.locate import locate_passage
    from app.rag.guardrails.detectors import mask_pii

    doc = db.execute(text("SELECT document_id, title, current_version_id, lifecycle_state FROM content.documents "
                          "WHERE document_id = :d AND deleted_at IS NULL"), {"d": document_id}).mappings().first()
    if doc is None:
        _audit(db, sec, "document_access", "preview_denied", "document", document_id, outcome="denied")
        raise NotFound("Document not found")
    passage = None
    if chunk_id:
        ch = db.execute(text("SELECT page_from, version_id, content FROM content.document_chunks WHERE chunk_id = :c AND document_id = :d"),
                        {"c": chunk_id, "d": document_id}).mappings().first()
        if ch is None:
            raise NotFound("Passage not found")
        page, version = ch["page_from"], ch["version_id"]
        passage = ch["content"]
    else:
        version = doc["current_version_id"]
    row = db.execute(text("""SELECT page_number, page_label, text, extraction, ocr_confidence, low_confidence
                               FROM content.document_pages WHERE version_id = :v AND page_number = :p"""),
                     {"v": version, "p": page or 1}).mappings().first()
    if row is None:
        raise NotFound("Page not found")
    masked, n = mask_pii(row["text"])
    # Locate the cited passage on the masked page, using the same masking on the passage so the offsets line up.
    highlight = locate_passage(masked, mask_pii(passage)[0]) if passage else None
    _audit(db, sec, "document_access", "preview", "document", document_id, {"page": row["page_number"], "masked": n})
    return {"document_id": document_id, "title": doc["title"], "version_id": version, "page_number": row["page_number"],
            "page_label": row["page_label"], "text": masked, "extraction": row["extraction"], "highlight": highlight,
            "ocr_confidence": row["ocr_confidence"], "low_confidence": row["low_confidence"],
            "pages_total": db.execute(text("SELECT count(*) FROM content.document_pages WHERE version_id = :v"),
                                      {"v": version}).scalar_one()}


# --- access management ---------------------------------------------------------------------
def set_document_access(db: Session, sec: SecurityContext, document_id: uuid.UUID, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace the document's platform-policy entries as a set (spec 10.3)."""
    if db.execute(text("SELECT 1 FROM content.documents WHERE document_id = :d"), {"d": document_id}).first() is None:
        raise NotFound("Document not found")
    db.execute(text("DELETE FROM content.document_access WHERE document_id = :d AND origin = 'platform_policy'"), {"d": document_id})
    for e in entries:
        db.execute(text("""INSERT INTO content.document_access (tenant_id, document_id, principal_type, principal_id, effect,
                                  origin, granted_by) VALUES (:t, :d, :pt, :pid, :ef, 'platform_policy', :by)"""),
                   {"t": sec.tenant_id, "d": document_id, "pt": e["principal_type"], "pid": e.get("principal_id"),
                    "ef": e.get("effect", "allow"), "by": sec.user_id})
    fp = db.execute(text("SELECT app.refresh_document_acl(:d)"), {"d": document_id}).scalar()
    invalidate_tenant_cache(sec.tenant_id)  # type: ignore[arg-type]
    _audit(db, sec, "authorization", "document_access_changed", "document", document_id,
           {"entries": len(entries), "acl_fingerprint": fp})
    return {"document_id": document_id, "acl_fingerprint": fp, "entries": list_document_access(db, document_id)}


def list_document_access(db: Session, document_id: uuid.UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text("""SELECT access_id, principal_type, principal_id, effect, origin, synced_at
                                                 FROM content.document_access WHERE document_id = :d ORDER BY synced_at"""),
                                        {"d": document_id}).mappings().all()]


# --- collections ------------------------------------------------------------------------------
def create_collection(db: Session, sec: SecurityContext, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("classification", "internal") not in CLASSIFICATIONS:
        raise ValidationFailed("invalid classification")
    quota_service.consume(db, sec, "collections")
    cid = uuid.uuid4()
    db.execute(text("""INSERT INTO content.collections (tenant_id, collection_id, code, name, description, department_id,
                              owner_user_id, line_of_business, jurisdictions, classification, retention_days, auto_publish,
                              created_by)
                       VALUES (:t, :c, :code, :name, :desc, :dep, :owner, :lob, :jur, :cls, :ret, :auto, :by)"""),
               {"t": sec.tenant_id, "c": cid, "code": data["code"], "name": data["name"], "desc": data.get("description"),
                "dep": data.get("department_id"), "owner": data.get("owner_user_id") or sec.user_id,
                "lob": data.get("line_of_business"), "jur": data.get("jurisdictions") or [],
                "cls": data.get("classification", "internal"), "ret": data.get("retention_days"),
                "auto": data.get("auto_publish", True), "by": sec.user_id})
    for grant in data.get("access") or []:
        _insert_collection_grant(db, sec, cid, grant)
    _audit(db, sec, "administration", "collection_created", "collection", cid, {"code": data["code"]})
    return get_collection(db, cid)


def _insert_collection_grant(db: Session, sec: SecurityContext, cid: uuid.UUID, grant: dict[str, Any]) -> None:
    db.execute(text("""INSERT INTO content.collection_access (tenant_id, collection_id, principal_type, principal_id, effect,
                              permission, granted_by) VALUES (:t, :c, :pt, :pid, :ef, :perm, :by)
                       ON CONFLICT DO NOTHING"""),
               {"t": sec.tenant_id, "c": cid, "pt": grant["principal_type"], "pid": grant.get("principal_id"),
                "ef": grant.get("effect", "allow"), "perm": grant.get("permission", "read"), "by": sec.user_id})


def get_collection(db: Session, collection_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("""SELECT c.*, (SELECT count(*) FROM content.documents d WHERE d.collection_id = c.collection_id
                                           AND d.deleted_at IS NULL) AS document_count,
                                    (SELECT COALESCE(sum(size_bytes), 0) FROM content.documents d
                                      WHERE d.collection_id = c.collection_id AND d.deleted_at IS NULL) AS storage_bytes
                               FROM content.collections c WHERE c.collection_id = :c"""), {"c": collection_id}).mappings().first()
    if row is None:
        raise NotFound("Collection not found")
    out = dict(row)
    out["access"] = [dict(r) for r in db.execute(text(
        "SELECT access_id, principal_type, principal_id, effect, permission FROM content.collection_access WHERE collection_id = :c"),
        {"c": collection_id}).mappings().all()]
    return out


def list_collections(db: Session) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text("""
        SELECT c.collection_id, c.code, c.name, c.description, c.line_of_business, c.jurisdictions, c.classification,
               c.status, c.auto_publish, c.department_id, c.owner_user_id, c.created_at,
               (SELECT count(*) FROM content.documents d WHERE d.collection_id = c.collection_id AND d.deleted_at IS NULL) AS document_count
          FROM content.collections c ORDER BY c.name""")).mappings().all()]


def update_collection(db: Session, sec: SecurityContext, collection_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {k: v for k, v in changes.items() if k in {"name", "description", "department_id", "owner_user_id",
                                                          "line_of_business", "jurisdictions", "classification",
                                                          "retention_days", "auto_publish", "status"} and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = :{k}" for k in allowed)
        res = db.execute(text(f"UPDATE content.collections SET {sets} WHERE collection_id = :cid"), {**allowed, "cid": collection_id})
        if res.rowcount == 0:
            raise NotFound("Collection not found")
    _audit(db, sec, "administration", "collection_updated", "collection", collection_id, {"changed": sorted(allowed)})
    return get_collection(db, collection_id)


def delete_collection(db: Session, sec: SecurityContext, collection_id: uuid.UUID) -> None:
    n = db.execute(text("SELECT count(*) FROM content.documents WHERE collection_id = :c"), {"c": collection_id}).scalar_one()
    if n:
        raise Conflict("Collection still contains documents; archive or move them first")
    res = db.execute(text("DELETE FROM content.collections WHERE collection_id = :c"), {"c": collection_id})
    if res.rowcount == 0:
        raise NotFound("Collection not found")
    quota_service.release(db, sec.tenant_id, "collections")  # type: ignore[arg-type]
    _audit(db, sec, "administration", "collection_deleted", "collection", collection_id)


def set_collection_access(db: Session, sec: SecurityContext, collection_id: uuid.UUID, grants: list[dict[str, Any]]) -> dict[str, Any]:
    get_collection(db, collection_id)
    db.execute(text("DELETE FROM content.collection_access WHERE collection_id = :c"), {"c": collection_id})
    for g in grants:
        _insert_collection_grant(db, sec, collection_id, g)
    docs = list(db.execute(text("SELECT document_id FROM content.documents WHERE collection_id = :c"), {"c": collection_id}).scalars())
    for d in docs:
        db.execute(text("SELECT app.refresh_document_acl(:d)"), {"d": d})
    invalidate_tenant_cache(sec.tenant_id)  # type: ignore[arg-type]
    _audit(db, sec, "authorization", "collection_access_changed", "collection", collection_id,
           {"grants": json.loads(json.dumps(grants, default=str)), "documents_refreshed": len(docs)})
    return get_collection(db, collection_id)


def collection_stats(db: Session, collection_id: uuid.UUID) -> dict[str, Any]:
    get_collection(db, collection_id)
    row = db.execute(text("""
        SELECT count(*) AS documents,
               count(*) FILTER (WHERE lifecycle_state = 'published') AS published,
               count(*) FILTER (WHERE lifecycle_state IN ('processing', 'draft', 'in_review')) AS pending,
               count(*) FILTER (WHERE lifecycle_state IN ('failed', 'quarantined')) AS failed,
               COALESCE(sum(size_bytes), 0) AS storage_bytes
          FROM content.documents WHERE collection_id = :c AND deleted_at IS NULL"""), {"c": collection_id}).mappings().one()
    jobs = db.execute(text("""SELECT j.status, count(*) FROM ingest.ingestion_jobs j JOIN content.documents d
                                ON d.document_id = j.document_id WHERE d.collection_id = :c GROUP BY j.status"""),
                      {"c": collection_id}).all()
    return {**dict(row), "ingestion_jobs": {s: n for s, n in jobs}}

