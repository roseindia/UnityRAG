"""Write docs/api/openapi.json and docs/api/API_REFERENCE.md from the FastAPI application."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402

spec = app.openapi()


def _routes(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from _routes(r.original_router.routes)


def _guards(dep, acc: list[str]) -> None:
    """Collect the RBAC guards (require / require_any / require_platform / admin) and their permissions."""
    qual = getattr(dep.call, "__qualname__", "") or ""
    kind = qual.split(".")[0]
    vals: list[str] = []
    for cell in getattr(dep.call, "__closure__", None) or ():
        try:
            v = cell.cell_contents
        except ValueError:
            continue
        if isinstance(v, tuple) and all(isinstance(x, str) for x in v):
            vals.extend(v)
    label = {"require": "tenant", "require_any": "tenant (any of)", "require_platform": "platform", "admin": "tenant admin"}.get(kind)
    if label and vals:
        acc.append(f"{label}: " + ", ".join(f"`{v}`" for v in vals))
    elif label == "platform":
        acc.append("platform role")
    elif kind in ("get_context", "get_tenant_context", "tenant_user") and not acc:
        acc.append("authenticated")
    for d in dep.dependencies:
        _guards(d, acc)


GUARDS: dict[tuple[str, str], str] = {}
for r in _routes(app.routes):
    acc: list[str] = []
    _guards(r.dependant, acc)
    if any(not a.startswith("authenticated") for a in acc):
        acc = [a for a in acc if a != "authenticated"]
    for m in r.methods or ():
        for full in spec["paths"]:
            if full.endswith(r.path) and m.lower() in spec["paths"][full] and \
                    spec["paths"][full][m.lower()].get("operationId", "").startswith(r.name):
                GUARDS[(m, full)] = "; ".join(dict.fromkeys(acc)) or "public"
out_dir = ROOT / "docs" / "api"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "openapi.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

by_tag: dict[str, list[tuple[str, str, dict]]] = {}
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        tag = (op.get("tags") or ["untagged"])[0]
        by_tag.setdefault(tag, []).append((method.upper(), path, op))

lines = ["# API reference", "",
         f"Generated from the FastAPI application by `scripts/generate_api_docs.py` "
         f"({len(spec['paths'])} paths). The machine-readable contract is `openapi.json` in this folder; "
         "a running API also serves it at `/api/v1/openapi.json` with Swagger UI at `/docs` and ReDoc at `/redoc` (all three are disabled when `ENVIRONMENT=production`).", "",
         "## Conventions", "",
         "- Base path: `/api/v1`. All bodies are JSON unless noted (uploads are `multipart/form-data`).",
         "- Authentication: `Authorization: Bearer <access token>` from `POST /api/v1/auth/login` (send `mfa_code` as well when the account has MFA enrolled; `/auth/mfa/verify` performs step-up later) or `POST /api/v1/auth/oidc/exchange`. "
         "Access tokens are short-lived JWTs; refresh with `POST /api/v1/auth/refresh` (refresh tokens rotate; reuse revokes the session family).",
         "- Tenant: derived **only** from the authenticated session. No endpoint accepts a tenant id for tenant-scoped data; "
         "platform endpoints under `/api/v1/platform/*` take a tenant id in the path because they act *on* a tenant and are restricted to platform roles.",
         "- Correlation: every response carries `X-Correlation-ID` (an incoming value is honoured if it is a safe token).",
         "- Errors: `{\"error\": {\"code\", \"message\", \"correlation_id\", \"details\"?}}` with an HTTP status matching the condition "
         "(400 validation, 401 unauthenticated, 403 forbidden, 404 not found or not visible, 409 conflict, 413 too large, 422 schema, 429 rate/quota limit).",
         "- Cross-tenant access returns **404** (not 403) so that the existence of another tenant's object is not disclosed.",
         "- Pagination: list endpoints take `limit` (bounded) and `offset`; responses include `items` and `total` where counting is cheap.",
         "- `tenant admin` endpoints additionally require a recent MFA step-up for write operations when the tenant setting "
         "`require_mfa_for_admin` is on; tenant administrators hold **no** document-content permission (SP-08).",
         "- Streaming: `POST /api/v1/chat/stream` (or `POST /api/v1/chat` with `\"stream\": true`) returns Server-Sent Events: `meta`, `token`*, `final`, `done` (or `error`). Tokens are released sentence-by-sentence only after the output guardrails pass for that sentence.", ""]
lines.append("## Endpoints by area\n")
for tag in sorted(by_tag):
    lines.append(f"### {tag}\n")
    lines.append("| Method | Path | Summary | Auth / permission |")
    lines.append("|---|---|---|---|")
    for method, path, op in sorted(by_tag[tag], key=lambda x: (x[1], x[0])):
        summary = (op.get("summary") or "").replace("|", "\\|")
        lines.append(f"| {method} | `{path}` | {summary} | {GUARDS.get((method, path), 'see handler')} |")
    lines.append("")


def _schema_name(sch: dict | None) -> str:
    if not sch:
        return "-"
    if "$ref" in sch:
        return "`" + sch["$ref"].split("/")[-1] + "`"
    if sch.get("type") == "array":
        return "array of " + _schema_name(sch.get("items"))
    if "anyOf" in sch:
        return " or ".join(_schema_name(x) for x in sch["anyOf"])
    return "`" + sch.get("type", "object") + "`"


def _example_value(sch: dict, depth: int = 0):
    if depth > 3 or not sch:
        return None
    if "$ref" in sch:
        return _example_value(spec["components"]["schemas"][sch["$ref"].split("/")[-1]], depth + 1)
    if "anyOf" in sch:
        return _example_value(next((x for x in sch["anyOf"] if x.get("type") != "null"), {}), depth)
    if "default" in sch:
        return sch["default"]
    if "enum" in sch:
        return sch["enum"][0]
    t = sch.get("type")
    if t == "object" or "properties" in sch:
        req = set(sch.get("required", []))
        props = sch.get("properties", {})
        keys = [k for k in props if k in req] or list(props)[:3]
        return {k: _example_value(props[k], depth + 1) for k in keys}
    if t == "array":
        return [_example_value(sch.get("items", {}), depth + 1)]
    fmt = sch.get("format")
    return {"string": {"uuid": "00000000-0000-0000-0000-000000000000", "date": "2026-01-01",
                       "date-time": "2026-01-01T00:00:00Z", "email": "user@example.com"}.get(fmt, "string"),
            "integer": 1, "number": 1.0, "boolean": True}.get(t, None)


lines.append("## Endpoint details\n")
lines.append("Errors listed are the ones the endpoint's guards and validation can produce; every error uses the envelope above. "
             "Examples use `$TOKEN` from `/auth/login`.\n")
for tag in sorted(by_tag):
    lines.append(f"### {tag} (details)\n")
    for method, path, op in sorted(by_tag[tag], key=lambda x: (x[1], x[0])):
        guard = GUARDS.get((method, path), "public")
        lines.append(f"#### `{method} {path}`\n")
        lines.append(f"- **Purpose:** {op.get('summary') or ''}. {(op.get('description') or '').strip().splitlines()[0] if op.get('description') else ''}".rstrip())
        lines.append(f"- **Authentication:** {'none' if guard == 'public' else 'Bearer access token'}")
        lines.append(f"- **Permission:** {guard}")
        params = op.get("parameters", [])
        if params:
            lines.append("- **Parameters:** " + ", ".join(
                f"`{p['name']}` ({p['in']}{', required' if p.get('required') else ''}: {_schema_name(p.get('schema'))})" for p in params))
        body = op.get("requestBody", {}).get("content", {})
        req_schema = None
        if body:
            ctype, media = next(iter(body.items()))
            req_schema = media.get("schema")
            lines.append(f"- **Request body:** {ctype} {_schema_name(req_schema)}")
        ok = next((c for c in op.get("responses", {}) if c.startswith("2")), None)
        if ok:
            content = op["responses"][ok].get("content", {})
            rs = next(iter(content.values()), {}).get("schema") if content else None
            ctype = next(iter(content), "") if content else ""
            lines.append(f"- **Success:** {ok} {ctype} {_schema_name(rs) if rs else ''}".rstrip())
        errs = []
        if guard != "public":
            errs += ["401 unauthenticated / expired token", "403 missing permission"]
        if "tenant admin" in guard:
            errs.append("401 `step_up_required` (writes, when MFA step-up is enforced)")
        if "{" in path:
            errs.append("404 not found or not visible to the caller")
        if params or body:
            errs.append("422 validation_failed")
        if path.endswith(("/auth/login", "/auth/mfa/verify", "/auth/refresh", "/auth/oidc/exchange")):
            errs.append("401 invalid credentials / token (`account_locked` after repeated failures)")
        if body and "multipart" in next(iter(body)):
            errs += ["413 request body over MAX_REQUEST_BYTES", "422 `unsupported_file_type` (content-signature check)",
                     "409 duplicate document", "429 `quota_exceeded` (document size / count / storage)"]
        errs.append("429 rate limit")
        lines.append("- **Errors:** " + "; ".join(errs))
        curl = f"curl -X {method} 'http://localhost:8000{path}'"
        if guard != "public":
            curl += " -H \"Authorization: Bearer $TOKEN\""
        if body and "json" in next(iter(body)):
            ex = _example_value(req_schema or {})
            curl += " -H 'Content-Type: application/json' -d '" + json.dumps(ex, default=str) + "'"
        elif body:
            ref = (req_schema or {}).get("$ref", "")
            form = spec["components"]["schemas"].get(ref.split("/")[-1], {}) if ref else {}
            for name in form.get("required", []):
                curl += " -F 'file=@policy.pdf'" if form["properties"][name].get("format") == "binary" or \
                    form["properties"][name].get("contentMediaType") else f" -F '{name}=<{name}>'"
            if "-F 'file=" not in curl:
                curl += " -F 'file=@policy.pdf'"
        lines.append(f"- **Example:** `{curl}`\n")

(out_dir / "API_REFERENCE.md").write_text("\n".join(lines), encoding="utf-8")
print(len(spec["paths"]), "paths;", sum(len(v) for v in by_tag.values()), "operations;", sorted(by_tag))
