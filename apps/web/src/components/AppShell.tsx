"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import { getMe } from "@/lib/api";
import { clearStoredAuth, getStoredAuth, storeAuth, type StoredAuth } from "@/lib/auth";

function currentPath(pathname: string): string {
  if (typeof window === "undefined") return pathname;
  return `${pathname}${window.location.search}`;
}

function loginPath(nextPath: string): string {
  return `/login?next=${encodeURIComponent(nextPath)}`;
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLoginRoute = pathname === "/login";
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (isLoginRoute) {
      setAuth(getStoredAuth());
      setChecking(false);
      return;
    }

    const stored = getStoredAuth();
    const nextPath = currentPath(pathname);
    if (!stored) {
      setAuth(null);
      setChecking(false);
      router.replace(loginPath(nextPath));
      return;
    }

    let cancelled = false;
    setAuth(stored);
    setChecking(true);

    getMe()
      .then((user) => {
        if (cancelled) return;
        const current = getStoredAuth();
        if (!current || current.token !== stored.token) return;
        const refreshed = { token: stored.token, user };
        storeAuth(refreshed);
        setAuth(refreshed);
      })
      .catch(() => {
        if (cancelled) return;
        clearStoredAuth();
        setAuth(null);
        router.replace(loginPath(nextPath));
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isLoginRoute, pathname, router]);

  const handleLogout = () => {
    clearStoredAuth();
    setAuth(null);
    router.replace("/login");
  };

  if (isLoginRoute) {
    return <>{children}</>;
  }

  if (checking || !auth) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg-primary)]">
        <div className="h-5 w-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  const displayName = auth.user.username || auth.user.name || auth.user.email;

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex h-12 shrink-0 items-center justify-end border-b border-[var(--border-subtle)] bg-[var(--bg-primary)] px-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="min-w-0 text-right leading-tight">
              <div className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                {displayName}
              </div>
              <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                {auth.user.role}
              </div>
            </div>
            <button type="button" onClick={handleLogout} className="btn-secondary px-3 py-1.5 text-[12px]">
              Logout
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </main>
    </div>
  );
}
