import { defineConfig } from '@playwright/test'

// Captures the screenshots used in docs/user-guide. The backend is replaced by an in-memory fake (capture.spec.ts),
// so the pictures show the real user interface with SAMPLE data. Run:  npx playwright test -c docs-shots
const channel = process.env.E2E_CHANNEL ?? 'chrome'

export default defineConfig({
  testDir: '.',
  timeout: 240_000,
  workers: 1,
  reporter: [['list']],
  use: { actionTimeout: 10_000, baseURL: 'http://localhost:5173', viewport: { width: 1280, height: 780 }, deviceScaleFactor: 1, ...(channel ? { channel } : {}) },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
    env: { VITE_API_BASE_URL: '/api/v1', VITE_ENABLE_MOCK_API: 'false', VITE_AUTH_MODES: 'local' },
  },
})
