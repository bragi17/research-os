"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";
import { storeAuth } from "@/lib/auth";

function nextPath(): string {
  if (typeof window === "undefined") return "/";
  const next = new URLSearchParams(window.location.search).get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  try {
    const url = new URL(next, window.location.origin);
    if (url.origin !== window.location.origin) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedIdentifier = identifier.trim();
    if (!trimmedIdentifier || !password) {
      setError("Enter your username/email and password.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await login(trimmedIdentifier, password);
      storeAuth({ token: response.access_token, user: response.user });
      router.replace(nextPath());
      router.refresh();
    } catch {
      setError("Invalid username/email or password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--bg-primary)] px-6 py-10">
      <div className="w-full max-w-[420px]">
        <div className="mb-7 text-center">
          <h1
            className="mb-2 text-3xl font-medium text-[var(--text-primary)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Research OS
          </h1>
          <p className="text-[14px] text-[var(--text-muted)]">Sign in to continue.</p>
        </div>

        <form onSubmit={handleSubmit} className="card-static p-5 shadow-sm">
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-semibold text-[var(--text-secondary)]">
                Username or email
              </span>
              <input
                className="input-field"
                type="text"
                autoComplete="username"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                disabled={loading}
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-[12px] font-semibold text-[var(--text-secondary)]">
                Password
              </span>
              <input
                className="input-field"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={loading}
              />
            </label>
          </div>

          {error && (
            <div className="mt-4 rounded-lg border border-[rgba(192,80,80,0.25)] bg-[var(--accent-red-soft)] px-3 py-2 text-[13px] text-[var(--accent-red)]">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn-primary mt-5 w-full"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                Signing in
              </span>
            ) : (
              "Sign in"
            )}
          </button>

          <div className="mt-4 border-t border-[var(--border-subtle)] pt-4">
            <button type="button" disabled className="btn-secondary w-full opacity-50">
              Register
            </button>
            <p className="mt-2 text-center text-[12px] text-[var(--text-muted)]">
              Registration is disabled for this deployment.
            </p>
          </div>
        </form>
      </div>
    </main>
  );
}
