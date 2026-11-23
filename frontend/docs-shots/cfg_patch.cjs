const fs = require('fs'); let s = fs.readFileSync('fakeBackend.ts', 'utf8')
const marker = "    if (path.startsWith('/admin/')) return json(route, {})"
if (!s.includes(marker)) throw new Error('marker')
const add = `    if (is('GET', /^\/admin\/config$/)) return json(route, { ai: cfg.ai[0], rag: cfg.rag[0], tenant_overridable_settings: null, available_models: MODELS })
    if (is('PUT', /^\/admin\/config\/(ai|rag)$/)) {
      const kind = path.endsWith('/ai') ? 'ai' : 'rag'
      const { reason, ...changes } = body
      const next = { ...cfg[kind][0], ...changes, version: cfg[kind][0].version + 1, change_reason: reason, created_at: iso() }
      cfg[kind].unshift(next)
      return json(route, next)
    }
    mm = path.match(/^\/admin\/config\/history\/(ai|rag)$/)
    if (mm) return json(route, cfg[mm[1] as 'ai' | 'rag'])
`
s = s.replace(marker, add + marker)
const data = `
const MODELS = [
  { provider: 'local', model_name: 'extractive-v1', purpose: 'chat', dimensions: null, status: 'active' },
  { provider: 'ollama-chat', model_name: 'llama3.1:8b', purpose: 'chat', dimensions: null, status: 'approved' },
  { provider: 'openai', model_name: 'gpt-4o-mini', purpose: 'chat', dimensions: null, status: 'approved' },
  { provider: 'local', model_name: 'hashing-v1', purpose: 'embedding', dimensions: 384, status: 'active' },
  { provider: 'ollama-embed', model_name: 'nomic-embed-text', purpose: 'embedding', dimensions: 768, status: 'approved' },
  { provider: 'openai', model_name: 'text-embedding-3-small', purpose: 'embedding', dimensions: 1536, status: 'approved' },
  { provider: 'local', model_name: 'lexical-overlap-v1', purpose: 'rerank', dimensions: null, status: 'active' },
  { provider: 'local', model_name: 'rule-rewriter-v1', purpose: 'rewrite', dimensions: null, status: 'active' },
]
export const cfg: { ai: R[]; rag: R[] } = {
  ai: [{ version: 1, llm_provider: 'local', chat_model: 'extractive-v1', embedding_provider: 'local', embedding_model: 'hashing-v1', embedding_dimensions: 384, reranker_provider: 'local', reranker_model: 'lexical-overlap-v1', rewrite_model: 'rule-rewriter-v1', temperature: 0.2, max_output_tokens: 1024, distance_metric: 'cosine', change_reason: 'initial provisioning', created_at: iso(60 * 24 * 30) }],
  rag: [{ version: 1, chunking_strategy: 'structure_aware', chunk_size: 350, chunk_overlap: 40, parent_child: true, vector_top_k: 30, fts_top_k: 30, exact_top_k: 10, vector_weight: 1, fts_weight: 1, exact_weight: 1.5, rrf_k: 60, rerank_enabled: true, rerank_top_n: 20, final_top_k: 6, max_context_tokens: 3000, min_relevance: 0, hnsw_ef_search: 100, citation_required: true, query_rewriting: true,
    guardrails: { prompt_injection: 'block', pii_output: 'mask', regulated_decision: 'block' }, change_reason: 'initial provisioning', created_at: iso(60 * 24 * 30) }],
}
`
s = s.replace("export interface State {", data + "\nexport interface State {")
fs.writeFileSync('fakeBackend.ts', s); console.log('ok')
