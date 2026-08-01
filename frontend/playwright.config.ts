import { defineConfig } from '@playwright/test'

const fixtureBaseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3101'
const selfHostedFixture = process.env.PLAYWRIGHT_E2E_SELF_HOSTED === '1'
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH

if (selfHostedFixture && fixtureBaseUrl !== 'http://127.0.0.1:3101') {
  throw new Error('PLAYWRIGHT_E2E_SELF_HOSTED requires PLAYWRIGHT_BASE_URL=http://127.0.0.1:3101')
}

export default defineConfig({
  testDir: './tests/agent-chat/e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: fixtureBaseUrl,
    headless: true,
    actionTimeout: 10000,
    launchOptions: executablePath ? { executablePath } : undefined,
  },
  webServer: selfHostedFixture
    ? {
        command: process.platform === 'win32' ? 'set PORT=3101&& npm run dev' : 'PORT=3101 npm run dev',
        url: fixtureBaseUrl,
        timeout: 120000,
        reuseExistingServer: false,
      }
    : undefined,
})
