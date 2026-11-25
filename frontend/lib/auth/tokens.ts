/**
 * Token storage. Demo choice: localStorage (see docs/DECISIONS.md).
 * A production build would keep the refresh token in an httpOnly cookie.
 */
const ACCESS_KEY = "careledger.access";
const REFRESH_KEY = "careledger.refresh";

export interface StoredTokens {
  accessToken: string;
  refreshToken: string;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readTokens(): StoredTokens | null {
  const s = storage();
  const accessToken = s?.getItem(ACCESS_KEY);
  const refreshToken = s?.getItem(REFRESH_KEY);
  return accessToken && refreshToken ? { accessToken, refreshToken } : null;
}

export function writeTokens(tokens: StoredTokens): void {
  const s = storage();
  s?.setItem(ACCESS_KEY, tokens.accessToken);
  s?.setItem(REFRESH_KEY, tokens.refreshToken);
}

export function clearTokens(): void {
  const s = storage();
  s?.removeItem(ACCESS_KEY);
  s?.removeItem(REFRESH_KEY);
}
