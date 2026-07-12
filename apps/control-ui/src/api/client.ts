import type { DataProvider } from "@refinedev/core";

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const KEYCLOAK_URL = (import.meta.env.VITE_KEYCLOAK_BASE_URL ?? import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8080").replace(/\/$/, "");
export const KEYCLOAK_REALM = import.meta.env.VITE_KEYCLOAK_REALM ?? "quant-team-os";
export const KEYCLOAK_CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "control-ui";

const ACCESS_TOKEN_KEY = "qto_access_token";
const REFRESH_TOKEN_KEY = "qto_refresh_token";
const ID_TOKEN_KEY = "qto_id_token";
const CODE_VERIFIER_KEY = "qto_pkce_verifier";
const STATE_KEY = "qto_auth_state";

export const RESOURCE_ENDPOINTS: Record<string, string> = {
  dashboard: "/api/v1/dashboard/summary",
  "research-pipeline": "/api/v1/research/pipeline",
  factors: "/api/v1/factors",
  strategies: "/api/v1/strategies",
  backtests: "/api/v1/backtests",
  reports: "/api/v1/research/reports",
  "agent-graph": "/api/v1/agent-graph",
  approvals: "/api/v1/approvals",
  connections: "/api/v1/connections",
  workflows: "/api/v1/workflows",
  "agent-runs": "/api/v1/agent-runs",
  "audit-log": "/api/v1/audit-logs",
  "tool-calls": "/api/v1/tool-calls",
  "policy-decisions": "/api/v1/policy-decisions",
  "external-workspaces": "/api/v1/external-workspaces",
  settings: "/api/v1/settings",
  "risk-reviews": "/api/v1/risk/reviews",
  "paper-sessions": "/api/v1/paper-trading/sessions",
};

export function storedAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function clearStoredAuth() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(ID_TOKEN_KEY);
  sessionStorage.removeItem(CODE_VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
}

export function readTokenUser(token: string | null) {
  if (!token) return null;
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const parsed = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return {
      username: parsed.preferred_username ?? parsed.email ?? parsed.sub,
      roles: parsed.realm_access?.roles ?? [],
    };
  } catch {
    return null;
  }
}

export async function readApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = storedAccessToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", headers.get("Content-Type") ?? "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function openApiPath(path: string) {
  const data = await readApi(path);
  return data;
}

export async function postApi<T>(path: string, payload: unknown): Promise<T> {
  return readApi<T>(path, { method: "POST", body: JSON.stringify(payload ?? {}) });
}

export async function patchApi<T>(path: string, payload: unknown): Promise<T> {
  return readApi<T>(path, { method: "PATCH", body: JSON.stringify(payload ?? {}) });
}

export async function putApi<T>(path: string, payload: unknown): Promise<T> {
  return readApi<T>(path, { method: "PUT", body: JSON.stringify(payload ?? {}) });
}

export async function readResourceList<T>(resource: string): Promise<T[]> {
  const path = RESOURCE_ENDPOINTS[resource] ?? resource;
  const value = await readApi<T[] | { items?: T[] }>(path);
  return Array.isArray(value) ? value : value.items ?? [];
}

export async function readResourceValue<T>(resourceOrPath: string): Promise<T> {
  const path = RESOURCE_ENDPOINTS[resourceOrPath] ?? resourceOrPath;
  return readApi<T>(path);
}

export const fastApiDataProvider: DataProvider = {
  getList: async ({ resource }) => {
    // Fetch once and reuse; deriving total from a second call doubled every
    // list request.
    const data = await readResourceList(resource);
    return { data, total: data.length };
  },
  getOne: async ({ resource, id }) => ({ data: await readResourceValue(`${RESOURCE_ENDPOINTS[resource] ?? resource}/${id}`) }),
  create: async ({ resource, variables }) => ({ data: await postApi(RESOURCE_ENDPOINTS[resource] ?? resource, variables) }),
  update: async ({ resource, id, variables }) => ({ data: await patchApi(`${RESOURCE_ENDPOINTS[resource] ?? resource}/${id}`, variables) }),
  deleteOne: async ({ resource, id }) => ({ data: await readApi(`${RESOURCE_ENDPOINTS[resource] ?? resource}/${id}`, { method: "DELETE" }) }),
  getApiUrl: () => API_URL,
};

export async function startKeycloakLoginRedirect() {
  const verifier = randomBase64Url(64);
  const state = randomBase64Url(32);
  sessionStorage.setItem(CODE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  const authUrl = new URL(`${KEYCLOAK_URL}/realms/${encodeURIComponent(KEYCLOAK_REALM)}/protocol/openid-connect/auth`);
  authUrl.searchParams.set("client_id", KEYCLOAK_CLIENT_ID);
  authUrl.searchParams.set("redirect_uri", `${window.location.origin}${window.location.pathname}`);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("scope", "openid profile email");
  authUrl.searchParams.set("state", state);
  authUrl.searchParams.set("code_challenge", await pkceChallenge(verifier));
  authUrl.searchParams.set("code_challenge_method", "S256");
  window.location.assign(authUrl.toString());
}

export async function finishKeycloakLoginIfNeeded() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  if (!code) return null;
  const state = url.searchParams.get("state");
  const expectedState = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(CODE_VERIFIER_KEY);
  if (!state || state !== expectedState || !verifier) {
    throw new Error("Keycloak state verification failed");
  }
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: KEYCLOAK_CLIENT_ID,
    code,
    redirect_uri: `${window.location.origin}${window.location.pathname}`,
    code_verifier: verifier,
  });
  const response = await fetch(`${KEYCLOAK_URL}/realms/${encodeURIComponent(KEYCLOAK_REALM)}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    throw new Error("Keycloak token exchange failed");
  }
  const token = await response.json();
  localStorage.setItem(ACCESS_TOKEN_KEY, token.access_token);
  if (token.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, token.refresh_token);
  if (token.id_token) localStorage.setItem(ID_TOKEN_KEY, token.id_token);
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  return token.access_token as string;
}

async function pkceChallenge(verifier: string) {
  const bytes = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return base64Url(new Uint8Array(digest));
}

function randomBase64Url(length: number) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

function base64Url(bytes: Uint8Array) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
