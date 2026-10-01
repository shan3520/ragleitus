import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: a real browser against the built UI, a running API and a
 * stub LLM. See "Frontend" in the README for how to start the API.
 *
 *   E2E_BASE_URL     UI to test (default: starts `next start` on :3000)
 *   E2E_LLM_URL      stub LLM base URL as the API sees it (default http://localhost:9999/v1)
 *   E2E_CHROMIUM     path to a Chromium binary, if Playwright's own is not installed
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: process.env.E2E_CHROMIUM ? { executablePath: process.env.E2E_CHROMIUM } : {},
      },
    },
  ],
  webServer: [
    {
      command: "node e2e/stub-llm.mjs",
      url: "http://localhost:9999/health",
      reuseExistingServer: true,
    },
    ...(process.env.E2E_BASE_URL
      ? []
      : [{ command: "npm run start", url: `${baseURL}/login`, reuseExistingServer: true, timeout: 60_000 }]),
  ],
});
