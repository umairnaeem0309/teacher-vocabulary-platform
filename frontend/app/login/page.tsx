"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { login } from "@/lib/search-client";

/**
 * Teacher sign-in (section 91): email + password against POST /auth/login;
 * the backend sets the HttpOnly session cookie. No client-side credential
 * storage. Bootstrap (first-teacher) flow is intentionally not offered in
 * the UI — the backend window closes permanently once one teacher exists.
 */
export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loginMutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (session) => {
      queryClient.setQueryData(["auth", "session"], { teacher: session.teacher });
      router.push(ROUTES.vocabulary);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    loginMutation.mutate();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold">Teacher sign in</h1>
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
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
            autoComplete="current-password"
            className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loginMutation.isPending}
          className="w-full rounded bg-neutral-900 px-3 py-2 text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {loginMutation.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
