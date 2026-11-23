"""Filtered vector-retrieval benchmark (extension 3.1): tenant-aware HNSW with RLS.

Creates N synthetic tenants with M chunks each (random unit vectors, 384 dims),
then for each tenant compares the ANN result (HNSW + hnsw.iterative_scan, under
the user RLS context) with exact brute-force results, reporting recall@10,
latency percentiles and the query plan.  Run against a dedicated database:

    cd backend && DB_NAME=rag_bench python -m app.database.bootstrap --drop-existing && \
        DB_NAME=rag_bench alembic upgrade head && DB_NAME=rag_bench python ../scripts/benchmark_vector.py --tenants 4 --chunks 10000
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402

from app.database.session import SecurityContext, scoped_session  # noqa: E402
from app.services import tenant_service  # noqa: E402

DIMS = 384
PLATFORM = SecurityContext(access_mode="platform", platform_role="platform_super_admin")


def unit(rng: random.Random) -> list[float]:
    v = [rng.gauss(0, 1) for _ in range(DIMS)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def lit(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def setup(n_tenants: int, n_chunks: int, rng: random.Random) -> list[dict]:
    out = []
    for i in range(n_tenants):
        with scoped_session(PLATFORM) as db:
            t = tenant_service.create_tenant(db, PLATFORM, code=f"bench-{i}-{uuid.uuid4().hex[:4]}", name=f"Bench {i}",
                                             legal_entity=None, plan_code="enterprise")
        tid = t["tenant_id"]
        principal = uuid.uuid4()
        with scoped_session(SecurityContext.worker(tid), role="worker") as db:
            cid, did, vid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.execute(text("INSERT INTO content.collections (tenant_id, collection_id, code, name) VALUES (:t, :c, 'bench', 'bench')"),
                       {"t": tid, "c": cid})
            db.execute(text("""INSERT INTO content.documents (tenant_id, document_id, collection_id, title, lifecycle_state,
                                      allow_principals) VALUES (:t, :d, :c, 'bench', 'published', ARRAY[CAST(:p AS uuid)])"""),
                       {"t": tid, "d": did, "c": cid, "p": str(principal)})
            db.execute(text("""INSERT INTO content.document_versions (tenant_id, version_id, document_id, version_seq, original_filename,
                                      storage_uri, checksum_sha256, size_bytes, mime_type, state)
                               VALUES (:t, :v, :d, 1, 'b.txt', 'x', repeat('0', 64), 0, 'text/plain', 'published')"""),
                       {"t": tid, "v": vid, "d": did})
            db.execute(text("UPDATE content.documents SET current_version_id = :v WHERE document_id = :d"), {"v": vid, "d": did})
            # COPY is refused on RLS-protected tables ("COPY FROM not supported with row-level
            # security"), so the loader uses batched INSERTs under the worker context.
            cur = db.connection().connection.driver_connection.cursor()
            ids = [uuid.uuid4() for _ in range(n_chunks)]
            cur.executemany("""INSERT INTO content.document_chunks (tenant_id, chunk_id, document_id, version_id, collection_id,
                                      chunk_index, content, content_hash, lifecycle_state, allow_principals)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, 'h', 'published', %s)""",
                            [(tid, ch, did, vid, cid, k, f"chunk {k}", [principal]) for k, ch in enumerate(ids)])
            cur.executemany("""INSERT INTO content.chunk_embeddings (tenant_id, chunk_id, document_id, model_name, dimensions,
                                      embedding, lifecycle_state, allow_principals)
                               VALUES (%s, %s, %s, 'bench', %s, %s::vector, 'published', %s)""",
                            [(tid, ch, did, DIMS, lit(unit(rng)), [principal]) for ch in ids])
        out.append({"tenant_id": tid, "principal": principal})
        print(f"tenant {i}: {n_chunks} chunks loaded", flush=True)
    return out


def run(tenants: list[dict], queries: int, ef: int, rng: random.Random) -> dict:
    results = {}
    for t in tenants:
        sec = SecurityContext(access_mode="user", tenant_id=t["tenant_id"], user_id=uuid.uuid4(),
                              principals=(t["principal"],), lobs=("*",), jurisdictions=("*",), max_class=3)
        recalls, lat = [], []
        plan = None
        for qn in range(queries):
            q = lit(unit(rng))
            with scoped_session(sec) as db:
                db.execute(text("SELECT set_config('hnsw.ef_search', :ef, true), set_config('hnsw.iterative_scan', 'relaxed_order', true)"),
                           {"ef": str(ef)})
                sql = f"""SELECT e.chunk_id FROM content.chunk_embeddings e
                           WHERE e.tenant_id = :t AND e.dimensions = {DIMS} AND e.is_active AND e.model_name = 'bench'
                           ORDER BY e.embedding::vector({DIMS}) <=> CAST(:q AS vector({DIMS})) LIMIT 10"""
                t0 = time.perf_counter()
                ann = [r[0] for r in db.execute(text(sql), {"t": t["tenant_id"], "q": q})]
                lat.append((time.perf_counter() - t0) * 1000)
                if plan is None:
                    plan = [r[0] for r in db.execute(text("EXPLAIN (COSTS OFF) " + sql), {"t": t["tenant_id"], "q": q})]
                db.execute(text("SET LOCAL enable_indexscan = off"))
                exact = [r[0] for r in db.execute(text(sql), {"t": t["tenant_id"], "q": q})]
            recalls.append(len(set(ann) & set(exact)) / 10)
        lat.sort()
        results[str(t["tenant_id"])] = {"recall_at_10": round(statistics.fmean(recalls), 4),
                                        "p50_ms": round(lat[len(lat) // 2], 2), "p95_ms": round(lat[int(len(lat) * .95) - 1], 2),
                                        "plan": plan}
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", type=int, default=4)
    ap.add_argument("--chunks", type=int, default=10000)
    ap.add_argument("--queries", type=int, default=50)
    ap.add_argument("--ef", type=int, default=100)
    a = ap.parse_args()
    rng = random.Random(42)
    t0 = time.time()
    tenants = setup(a.tenants, a.chunks, rng)
    print(f"load: {time.time() - t0:.1f}s", flush=True)
    res = run(tenants, a.queries, a.ef, rng)
    summary = {"tenants": a.tenants, "chunks_per_tenant": a.chunks, "total_vectors": a.tenants * a.chunks, "dims": DIMS,
               "ef_search": a.ef, "per_tenant": res,
               "mean_recall_at_10": round(statistics.fmean(r["recall_at_10"] for r in res.values()), 4)}
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
