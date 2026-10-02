import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/**
 * Global setup for the end-to-end acceptance suite (sections 59-61, 103).
 *
 * 1. Runs scripts/phase27_seed_acceptance.py so every run starts from the
 *    same known state (acceptance teacher, student John with overdue cards).
 * 2. Turns the seed's server-minted session token into a browser storage
 *    state file, which every test context loads. Only §59's explicit
 *    "login as teacher" step performs a real HTTP login — the login rate
 *    limit (§39: 10 per 5 minutes per IP) would otherwise be burned by
 *    the whole suite, especially across quick re-runs.
 *
 * The seed talks straight to PostgreSQL, so setup works regardless of
 * whether the web servers are up yet.
 */

const COOKIE_NAME = "session_token";
// Same host the page will fetch from — same-site matters for SameSite=Lax.
const BACKEND_HOST = new URL(
  process.env.E2E_BACKEND_URL ?? "http://localhost:8737",
).hostname;

interface SeedOutput {
  teacher_id?: string;
  john_student_id?: string;
  session_token?: string;
}

export default function globalSetup(): void {
  const backendDir = path.resolve(__dirname, "..", "..", "backend");
  const result = spawnSync(
    "uv run python ../scripts/phase27_seed_acceptance.py",
    {
      cwd: backendDir,
      shell: true,
      encoding: "utf-8",
      env: {
        ...process.env,
        PYTHONPATH: "..",
        PYTHONIOENCODING: "utf-8",
      },
    },
  );

  if (result.status !== 0) {
    throw new Error(
      `acceptance seed failed (exit ${result.status}):\n${result.stderr || result.stdout}`,
    );
  }

  const lines = (result.stdout ?? "").trim().split(/\r?\n/);
  const jsonLine = [...lines].reverse().find((l) => l.trim().startsWith("{"));
  if (!jsonLine) {
    throw new Error(`acceptance seed printed no JSON:\n${result.stdout}`);
  }
  const info = JSON.parse(jsonLine) as SeedOutput;
  if (!info.session_token) {
    throw new Error(`acceptance seed returned no session token:\n${jsonLine}`);
  }

  const storageState = {
    cookies: [
      {
        name: COOKIE_NAME,
        value: info.session_token,
        domain: BACKEND_HOST,
        path: "/",
        expires: Math.floor(Date.now() / 1000) + 24 * 3600,
        httpOnly: true,
        secure: false,
        sameSite: "Lax" as const,
      },
    ],
    origins: [],
  };
  const statePath = path.resolve(__dirname, "storage-state.json");
  fs.writeFileSync(statePath, JSON.stringify(storageState, null, 2));

  console.log(
    `seeded acceptance fixtures (teacher ${info.teacher_id}, ` +
      `John ${info.john_student_id}); storage state -> ${statePath}`,
  );
}
