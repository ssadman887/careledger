"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { clearTokens, readTokens, writeTokens } from "@/lib/auth/tokens";
import type { RoleName } from "@/lib/roles";

export type CurrentUser = Schemas["UserOut"];

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  roles: RoleName[];
  login: (login: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    if (!readTokens()) {
      setUser(null);
      setLoading(false);
      return;
    }
    const { data } = await api.GET("/api/v1/auth/me");
    setUser(data ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadMe();
    const onLogout = () => {
      clearTokens();
      setUser(null);
      router.replace("/login");
    };
    window.addEventListener("careledger:logout", onLogout);
    return () => window.removeEventListener("careledger:logout", onLogout);
  }, [loadMe, router]);

  const login = useCallback(
    async (loginName: string, password: string): Promise<string | null> => {
      const { data, error } = await api.POST("/api/v1/auth/login", {
        body: { login: loginName, password },
      });
      if (!data) return errorMessage(error, "Login failed");
      writeTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
      await loadMe();
      return null;
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    const tokens = readTokens();
    if (tokens) {
      await api.POST("/api/v1/auth/logout", { body: { refresh_token: tokens.refreshToken } });
    }
    clearTokens();
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo<AuthState>(
    () => ({ user, loading, roles: (user?.roles ?? []) as RoleName[], login, logout }),
    [user, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
