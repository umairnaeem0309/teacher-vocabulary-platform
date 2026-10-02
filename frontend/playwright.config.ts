import path from "node:path";

import { defineConfig } from "@playwright/test";

/**
 * End-to-end acceptance configuration (master_prompt.md sections 59-61, 103).
 *
 * Drives the real UI in the installed system Chrome against the local dev
 * stack (local-only scope, D026). Servers are started on demand:
 *
 *   - backend  :8737  (uvicorn, PYTHONPATH=..) — reused when already up
 *   - frontend :3000  (next dev, NEXT_PUBLIC_API_URL -> backend) — always
 *                     started fresh, never a stale build
 *
 * Both hosts are `localhost` on purpose: the page and the API must be
 * same-site or the SameSite=Lax session cookie would never be attached to
 * cross-site fetches and every authenticated call would 401.
 *
 * Run:  cd frontend && pnpm exec playwright test
 *
 * Global setup seeds the fixtures and writes e2e/storage-state.json; every
 * context starts already authenticated with that session (only §59 spends a
 * real HTTP login, keeping runs under the §39 login rate limit).
 */
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? "http://localhost:8737";
const FRONTEND_URL = "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  // The suite shares one teacher account and one PostgreSQL database.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: FRONTEND_URL,
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
    navigationTimeout: 60_000,
    actionTimeout: 30_000,
    // Written by global setup (seed-minted session cookie for the API host).
    storageState: "./e2e/storage-state.json",
  },
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8737 --host 127.0.0.1",
      cwd: path.resolve(__dirname, "..", "backend"),
      url: `${BACKEND_URL}/api/v1/health`,
      reuseExistingServer: true,
      timeout: 120_000,
      env: { PYTHONPATH: "..", PYTHONIOENCODING: "utf-8" },
    },
    {
      // Always (re)start the frontend: a stale `next start` build on :3000
      // would have NEXT_PUBLIC_API_URL baked in at build time (pointing at
      // a dead port) and every API call in the suite would silently fail.
      command: "pnpm dev --port 3000",
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { NEXT_PUBLIC_API_URL: BACKEND_URL },
    },
  ],
});
