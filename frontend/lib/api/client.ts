import createClient, { type Middleware } from "openapi-fetch";

import { clearTokens, readTokens, writeTokens } from "@/lib/auth/tokens";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type ApiErrorBody = Schemas["ErrorEnvelope"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Typed client generated from FastAPI's OpenAPI spec (never hand-write API types). */
export const api = createClient<paths>({ baseUrl: API_URL });

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const tokens = readTokens();
  if (!tokens) return false;
  const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refreshToken }),
  });
  if (!res.ok) {
    clearTokens();
    return false;
  }
  const body = (await res.json()) as Schemas["TokenPair"];
  writeTokens({ accessToken: body.access_token, refreshToken: body.refresh_token });
  return true;
}

const PUBLIC_PATHS = ["/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const tokens = readTokens();
    if (tokens && !PUBLIC_PATHS.some((p) => request.url.includes(p))) {
      request.headers.set("Authorization", `Bearer ${tokens.accessToken}`);
    }
    return request;
  },
  async onResponse({ request, response }) {
    if (response.status !== 401 || PUBLIC_PATHS.some((p) => request.url.includes(p))) {
      return response;
    }
    refreshing ??= refreshTokens().finally(() => {
      refreshing = null;
    });
    if (!(await refreshing)) {
      if (typeof window !== "undefined") window.dispatchEvent(new Event("careledger:logout"));
      return response;
    }
    const retry = request.clone();
    retry.headers.set("Authorization", `Bearer ${readTokens()?.accessToken ?? ""}`);
    return fetch(retry);
  },
};

api.use(authMiddleware);

/** Extract a human-readable message from the API error envelope. */
export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error && typeof error === "object" && "error" in error) {
    const body = (error as ApiErrorBody).error;
    if (body?.message) return body.message;
  }
  return fallback;
}
