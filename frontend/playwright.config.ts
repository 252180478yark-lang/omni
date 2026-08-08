import { defineConfig } from '@playwright/test'

const fixtureBaseUrl = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3101'
const selfHostedFixture = process.env.PLAYWRIGHT_E2E_SELF_HOSTED === '1'
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH
const fixtureUrl = new URL(fixtureBaseUrl)
const fixturePort = Number(fixtureUrl.port || '80')

if (selfHostedFixture && !['127.0.0.1', 'localhost'].includes(fixtureUrl.hostname)) {
  throw new Error('PLAYWRIGHT_E2E_SELF_HOSTED requires a loopback PLAYWRIGHT_BASE_URL')
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
        command: process.platform === 'win32' ? `set PORT=${fixturePort}&& npm run dev` : `PORT=${fixturePort} npm run dev`,
        url: fixtureBaseUrl,
        timeout: 120000,
        reuseExistingServer: false,
      }
    : undefined,
})
