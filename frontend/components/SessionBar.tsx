"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { fetchSession, logout } from "@/lib/search-client";
import { ROUTES } from "@/lib/routes";

/**
 * Compact teacher session indicator for workbench pages (section 39):
 * authenticated teacher on the right, logout action, sign-in link when
 * logged out. Errors (401) intentionally render as signed-out.
 */
export function SessionBar() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    retry: false,
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData(["auth", "session"], undefined);
      queryClient.clear();
    },
  });

  const teacher = session.data?.teacher;

  return (
    <div className="flex items-center justify-end gap-3 px-4 py-2 text-sm">
      {teacher ? (
        <>
          <span className="text-neutral-600">{teacher.display_name}</span>
          <button
            type="button"
            className="rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            {logoutMutation.isPending ? "Signing out…" : "Sign out"}
          </button>
        </>
      ) : (
        <Link
          href={ROUTES.login}
          className="rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
        >
          Sign in
        </Link>
      )}
    </div>
  );
}
