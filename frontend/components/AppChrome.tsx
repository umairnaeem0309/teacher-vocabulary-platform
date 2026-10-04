"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactElement } from "react";

import { SessionBar } from "@/components/SessionBar";
import { ApiError } from "@/lib/api";
import { ROUTES } from "@/lib/routes";
import { fetchSession } from "@/lib/search-client";

/**
 * Global application chrome (HCI shell): persistent navigation, session
 * controls and an authentication guard shared by every workbench route.
 *
 * - Desktop (≥1024px): fixed left sidebar with brand, primary navigation
 *   and the session block; content is offset with `lg:pl-60`.
 * - Below that: sticky two-row header (brand + session, then a horizontally
 *   scrollable nav row) — content flows below it naturally.
 * - The session query doubles as the auth guard: a 401 (signed out or
 *   expired) forwards to /login once fetched. Network failures do not
 *   redirect — the pages surface their own connection errors instead.
 * - `/` and `/login` render bare (the root route redirects itself and the
 *   sign-in page is intentionally full-screen).
 */

interface NavItem {
  label: string;
  href: string;
  icon: ReactElement;
}

const ICON = {
  className: "h-[18px] w-[18px] shrink-0",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const NAV: NavItem[] = [
  {
    label: "Dashboard",
    href: ROUTES.dashboard,
    icon: (
      <svg {...ICON}>
        <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
        <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
        <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
        <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
      </svg>
    ),
  },
  {
    label: "Vocabulary",
    href: ROUTES.vocabulary,
    icon: (
      <svg {...ICON}>
        <path d="M12 6.5C10.5 5 8.5 4.5 4 4.5v14c4.5 0 6.5.5 8 2 1.5-1.5 3.5-2 8-2v-14c-4.5 0-6.5.5-8 2z" />
        <path d="M12 6.5v14" />
      </svg>
    ),
  },
  {
    label: "Students",
    href: ROUTES.students,
    icon: (
      <svg {...ICON}>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" />
      </svg>
    ),
  },
  {
    label: "Sets",
    href: ROUTES.sets,
    icon: (
      <svg {...ICON}>
        <path d="M12 3l8 4.5-8 4.5-8-4.5L12 3z" />
        <path d="M4 12l8 4.5 8-4.5" />
        <path d="M4 16.5L12 21l8-4.5" />
      </svg>
    ),
  },
  {
    label: "Settings",
    href: ROUTES.settings,
    icon: (
      <svg {...ICON}>
        <path d="M4 7h16" />
        <path d="M4 12h16" />
        <path d="M4 17h16" />
        <circle cx="9" cy="7" r="2" />
        <circle cx="15" cy="12" r="2" />
        <circle cx="8" cy="17" r="2" />
      </svg>
    ),
  },
];

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-neutral-900 text-sm font-bold text-white"
      >
        V
      </span>
      {!compact && (
        <span className="text-sm font-semibold leading-tight tracking-tight">
          Vocabulary Workbench
        </span>
      )}
    </span>
  );
}

export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    retry: false,
  });

  const bare = pathname === "/" || pathname === ROUTES.login;

  // Auth guard: signed out (401) → sign-in page, exactly once per fetch.
  useEffect(() => {
    if (bare || !session.isFetched) return;
    if (session.error instanceof ApiError && session.error.status === 401) {
      router.replace(ROUTES.login);
    }
  }, [bare, session.isFetched, session.error, router]);

  if (bare) return <>{children}</>;

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-neutral-900 focus:px-4 focus:py-2 focus:text-sm focus:text-white"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-neutral-200 bg-white lg:flex">
        <Link
          href={ROUTES.dashboard}
          className="flex h-16 items-center border-b border-neutral-100 px-4"
        >
          <Brand />
        </Link>
        <nav className="flex-1 space-y-1 p-3" aria-label="Main navigation">
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  active
                    ? "bg-neutral-900 text-white shadow-sm"
                    : "text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-neutral-100">
          <SessionBar />
        </div>
      </aside>

      {/* Mobile header (sticky — occupies normal flow, no content offset) */}
      <header className="sticky top-0 z-30 border-b border-neutral-200 bg-white lg:hidden">
        <div className="flex h-14 items-center gap-2 overflow-x-auto px-3">
          <Link href={ROUTES.dashboard} className="shrink-0">
            <Brand compact />
          </Link>
          <span className="hidden text-sm font-semibold sm:inline">
            Vocabulary Workbench
          </span>
          <div className="ml-auto shrink-0">
            <SessionBar />
          </div>
        </div>
        <nav
          className="flex gap-1 overflow-x-auto border-t border-neutral-100 px-2 py-1.5"
          aria-label="Main navigation"
        >
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-neutral-900 text-white"
                    : "text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <div
        id="main-content"
        tabIndex={-1}
        className="focus:outline-none lg:pl-60"
      >
        {children}
      </div>
    </div>
  );
}
