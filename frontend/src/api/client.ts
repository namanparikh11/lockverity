/**
 * Lockverity API client.
 *
 * - Configurable base URL via Vite env (`VITE_API_BASE_URL`).
 * - Typed responses mirroring the backend Pydantic schemas.
 * - Structured error parsing: every error carries a stable `code`
 *   so the UI can show a useful message without parsing the human
 *   description.
 * - Request cancellation via `AbortController`.
 * - No credentials, no tokens, no production fixture fallback.
 */

const DEFAULT_BASE_URL = "/api/v1";

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  requestId?: string;
  httpStatus: number;
}

export class ApiClientError extends Error {
  public readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(apiError.message);
    this.name = "ApiClientError";
    this.apiError = apiError;
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
}

function readBaseUrl(): string {
  // Vite injects only vars that begin with VITE_.
  const env = (import.meta as unknown as { env?: Record<string, unknown> }).env;
  const fromEnv = env?.VITE_API_BASE_URL;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.replace(/\/+$/, "");
  }
  return DEFAULT_BASE_URL;
}

function buildUrl(
  base: string,
  path: string,
  query?: RequestOptions["query"]
): string {
  const url = new URL(
    path.startsWith("/") ? `${base}${path}` : `${base}/${path}`,
    window.location.origin
  );
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = "Request failed.";
  let details: Record<string, unknown> | undefined;
  let requestId: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: {
        code?: string;
        message?: string;
        details?: Record<string, unknown>;
        request_id?: string;
      };
    };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
      requestId = body.error.request_id;
    }
  } catch {
    // Non-JSON error body. The defaults above are safe.
  }
  if (response.headers.get("x-request-id")) {
    requestId = response.headers.get("x-request-id") ?? requestId;
  }
  return {
    code,
    message,
    details,
    requestId,
    httpStatus: response.status,
  };
}

async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
  body?: unknown
): Promise<T> {
  const base = readBaseUrl();
  const url = buildUrl(base, path, options.query);
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers ?? {}),
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const init: RequestInit = {
    method,
    headers,
    signal: options.signal ?? null,
    credentials: "omit",
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new ApiClientError(await parseError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const apiClient = {
  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>("GET", path, options);
  },
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>("POST", path, options, body);
  },
};

export function describeError(err: unknown): string {
  if (err instanceof ApiClientError) {
    return err.apiError.message;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Unknown error.";
}
