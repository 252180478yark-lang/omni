import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/agent-chat/e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    actionTimeout: 10000,
  },
})
