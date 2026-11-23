# UnityRAG: frontend

React + TypeScript single-page application for the UnityRAG platform: the **User Workspace** (chat with cited answers, search, documents), the **Tenant Admin Console** and the **Platform Admin Console**. It implements `docs/frontend/Frontend_Design_Document.docx` against the backend described in `docs/api/openapi.json`.

The frontend holds no authorisation logic of its own. It hides controls a user cannot use, and the backend authorises every request again (RBAC, ABAC, PostgreSQL row-level security).

## Requirements

- Node.js 20 or newer (built and tested with Node 20.12 and npm 10)
- A running backend on `VITE_API_BASE_URL` for real use (see "Running without a backend")
- For the end-to-end tests: Google Chrome (or Edge), no browser download needed

## Commands

```bash
npm install
npm install --no-fund
npm run dev          # http://localhost:5173
npm run build        # type-checks (tsc) then builds to dist/
npm run lint         # ESLint (typescript-eslint, react-hooks, jsx-a11y), zero warnings allowed
npm run typecheck    # tsc, strict mode
npm run test         # Vitest: unit and integration tests
npm run test:e2e     # Playwright journeys in Chrome (backend stubbed at the network layer)
```

`E2E_CHANNEL=msedge npm run test:e2e` uses Edge; `E2E_CHANNEL= npm run test:e2e` uses a Playwright-downloaded browser (`npx playwright install chromium` first).

## Configuration

Copy `.env.example` to `.env`. All values are read at build/start time; there are no secrets.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend API prefix. Use `/api/v1` behind a same-origin proxy (recommended; avoids CORS) |
| `VITE_APP_NAME` | `UnityRAG` | Name shown in the UI |
| `VITE_ENABLE_MOCK_API` | `false` | Development-only sample data (see below) |
| `VITE_AUTH_MODES` | `local` | `local`, `oidc` or `local,oidc`; must match the backend `AUTH_MODE` |
| `VITE_OIDC_START_URL`, `VITE_OIDC_DISPLAY_NAME` | empty | Where the SSO button goes, and its label |
| `VITE_CHAT_STREAMING` | `true` | `false` uses `POST /chat` instead of server-sent events |
| `VITE_SESSION_IDLE_MINUTES` | `30` | Idle warning timeout (until `/auth/me` exposes the tenant value) |
| `VITE_SUPPORT_URL`, `VITE_USAGE_POLICY_URL` | empty | Help and AI-usage links |

## Running without a backend

```bash
VITE_ENABLE_MOCK_API=true npm run dev
```

Sign in with an email starting `member`, `admin` or `platform` and any password to get that persona. A badge in the corner says **MOCK API: development sample data**. Only a handful of endpoints are mocked; all others answer 404 so gaps are visible. The mock is not part of the production build.

## Project layout

```
src/
  app/            router, providers, query client, route guards
  components/     ui (primitives), layout, feedback, common, tables, charts, forms, dialogs, rag
  features/       authentication, dashboard, chat, search, documents, ingestion, conversations,
                  analytics, tenant-admin, platform-admin
  services/api/   Axios client, SSE client, error catalogue, one module per API area
  services/authentication/   in-memory token store
  contexts/ hooks/ schemas/ types/ utils/ constants/ config/ styles/
tests/            unit, integration (React Testing Library), e2e (Playwright)
docs/             analysis, page inventory, component catalog, plans, API mapping, implementation report
```

## Security notes

- Access and refresh tokens are held **in memory only**. A page reload signs the user out. The design document's authentication BFF (HttpOnly refresh cookie) is not part of this deliverable.
- No tenant id is sent in tenant-scoped requests. Caches are cleared on logout, session expiry and tenant switch.
- Search highlights pass through DOMPurify (only `<mark>` survives); answers are rendered as markdown without raw HTML; ESLint forbids `dangerouslySetInnerHTML` outside `SafeHighlight`.
- API keys are write-only in the UI. Downloads use the bearer header, never a token in the URL.
- A strict Content-Security-Policy needs `style-src-attr 'unsafe-inline'` (progress bars and Recharts use inline styles) until those are refactored.

## Documentation

| File | Content |
|---|---|
| `docs/FRONTEND_REQUIREMENTS_ANALYSIS.md` | What the design requires, deviations and why |
| `docs/FRONTEND_PAGE_INVENTORY.md` | Every page: route, roles, API, validation, states |
| `docs/FRONTEND_COMPONENT_CATALOG.md` | Reusable components and the mapping to the design's inventory |
| `docs/FRONTEND_IMPLEMENTATION_PLAN.md` | Phases, status, defects found by testing |
| `docs/FRONTEND_API_INTEGRATION_PLAN.md` | How the client talks to the backend |
| `docs/API_INTEGRATION_MAPPING.md` | All 153 operations, status, BACKEND_REQUIRED items |
| `docs/FRONTEND_IMPLEMENTATION_REPORT.md` | Results: what works, what was verified, known limitations |

## Known limitations

See "Known limitations" in `docs/FRONTEND_IMPLEMENTATION_REPORT.md`. The most important: it has **not been run against a live backend**, it has no BFF, and it is not localisation-ready.
