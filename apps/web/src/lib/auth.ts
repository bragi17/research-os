import type { User } from "@/lib/api";

export interface StoredAuth {
  token: string;
  user: User;
}

const TOKEN_KEY = "token";
const USER_KEY = "research_os_user";

export function getStoredAuth(): StoredAuth | null {
  if (typeof window === "undefined") return null;

  const token = localStorage.getItem(TOKEN_KEY);
  const rawUser = localStorage.getItem(USER_KEY);
  if (!token || !rawUser) return null;

  try {
    return { token, user: JSON.parse(rawUser) as User };
  } catch {
    clearStoredAuth();
    return null;
  }
}

export function storeAuth(auth: StoredAuth): void {
  localStorage.setItem(TOKEN_KEY, auth.token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearStoredAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
