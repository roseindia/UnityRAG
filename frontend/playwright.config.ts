import { defineConfig } from '@playwright/test'

// The specs stub the backend at the network layer (tests/e2e/helpers.ts), so no backend is needed.
// They use the locally installed Chrome (channel "chrome"); set E2E_CHANNEL=msedge, or "" to use a downloaded Playwright browser.
const channel = process.env.E2E_CHANNEL ?? 'chrome'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5173', trace: 'retain-on-failure', ...(channel ? { channel } : {}) },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: false,
    timeout: 60_000,
    // Same-origin API path so Playwright can intercept without CORS; mock adapter off.
    env: { VITE_API_BASE_URL: '/api/v1', VITE_ENABLE_MOCK_API: 'false', VITE_AUTH_MODES: 'local' },
  },
})
