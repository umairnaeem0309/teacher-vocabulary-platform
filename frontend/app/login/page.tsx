"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { bootstrap, login } from "@/lib/search-client";

interface Teacher {
  id: string;
  email: string;
  display_name: string;
}

/**
 * Teacher sign-in (section 91): email + password against POST /auth/login;
 * the backend sets the HttpOnly session cookie. No client-side credential
 * storage.
 *
 * First run: "Create the first teacher account" posts to POST /auth/bootstrap
 * (one-time window — the backend returns 403 `bootstrap_closed` forever after
 * the first teacher exists, and the form folds back into sign-in with an
 * explanatory message).
 */
export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"login" | "bootstrap">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function finish(teacher: Teacher) {
    queryClient.setQueryData(["auth", "session"], { teacher });
    // Post-login landing = the dashboard (home base for the whole app).
    router.push(ROUTES.dashboard);
  }

  const loginMutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (session) => finish(session.teacher),
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
    },
  });

  const bootstrapMutation = useMutation({
    mutationFn: () => bootstrap(email, password, displayName.trim()),
    onSuccess: (result) => finish(result.teacher),
    onError: (err) => {
      if (err instanceof ApiError && err.code === "bootstrap_closed") {
        setMode("login");
        setError("A teacher account already exists — sign in instead.");
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "Account creation failed — is the backend running on port 8000?",
      );
    },
  });

  const pending = loginMutation.isPending || bootstrapMutation.isPending;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (mode === "bootstrap") {
      bootstrapMutation.mutate();
    } else {
      loginMutation.mutate();
    }
  }

  function switchMode(next: "login" | "bootstrap") {
    setMode(next);
    setError(null);
  }

  const creating = mode === "bootstrap";

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold">
        {creating ? "Create teacher account" : "Teacher sign in"}
      </h1>
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {creating && (
          <label className="block">
            <span className="text-sm text-neutral-700">Display name</span>
            <input
              type="text"
              required
              maxLength={200}
              autoComplete="name"
              className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </label>
        )}
        <label className="block">
          <span className="text-sm text-neutral-700">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-sm text-neutral-700">Password</span>
          <input
            type="password"
            required
            minLength={creating ? 10 : undefined}
            autoComplete={creating ? "new-password" : "current-password"}
            className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded bg-neutral-900 px-3 py-2 text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {pending
            ? creating
              ? "Creating…"
              : "Signing in…"
            : creating
              ? "Create account"
              : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-sm text-neutral-600">
        {creating ? (
          <>
            Already have an account?{" "}
            <button
              type="button"
              className="text-blue-700 underline"
              onClick={() => switchMode("login")}
            >
              Back to sign in
            </button>
          </>
        ) : (
          <>
            No account yet?{" "}
            <button
              type="button"
              className="text-blue-700 underline"
              onClick={() => switchMode("bootstrap")}
            >
              Create the first teacher account
            </button>
          </>
        )}
      </p>
      <p className="mt-2 text-xs text-neutral-500">
        First run only: the platform has a single teacher account — the create
        window closes permanently once one exists.
      </p>
    </main>
  );
}
