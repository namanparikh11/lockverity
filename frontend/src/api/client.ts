/**
 * Lockverity API client.
 *
 * - Configurable base URL via Vite env (`VITE_API_BASE_URL`).
 * - Typed responses mirroring the backend Pydantic schemas.
 * - Structured error parsing: every error carries a stable `code`
 *   so the UI can show a useful message without parsing the human
 *   description.
 * - Request cancellation via `AbortController`.
 * - Timeout handling: requests abort after a configurable
 *   `VITE_API_TIMEOUT_MS` (default 30 000 ms).
 * - No credentials, no tokens, no production fixture fallback.
 * - Development-only fixtures may exist behind
 *   `VITE_DEV_FIXTURES=enabled` and must never activate due to
 *   API failure.
 */

const DEFAULT_BASE_URL = "/api/v1";
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 120_000;

/**
 * The only development-flag the API client recognises. A typo
 * (`VITE_DEV_FIXTURE=enabled`) MUST NOT activate fixtures; the
 * value must be exactly the string "enabled" (case-sensitive).
 */
const DEV_FIXTURE_FLAG = "enabled";

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  requestId?: string;
  httpStatus: number;
}

export class ApiClientError extends Error {
  public readonly apiError: ApiError;
  public readonly isAbort: boolean;
  public readonly isTimeout: boolean;

  constructor(apiError: ApiError, options: { isAbort?: boolean; isTimeout?: boolean } = {}) {
    super(apiError.message);
    this.name = "ApiClientError";
    this.apiError = apiError;
    this.isAbort = options.isAbort ?? false;
    this.isTimeout = options.isTimeout ?? false;
  }
}

export class ApiAbortError extends ApiClientError {
  constructor(message = "Request was cancelled.") {
    super(
      {
        code: "cancelled",
        message,
        httpStatus: 0,
      },
      { isAbort: true }
    );
    this.name = "ApiAbortError";
  }
}

export class ApiTimeoutError extends ApiClientError {
  constructor(timeoutMs: number) {
    super(
      {
        code: "timeout",
        message: `Request did not complete within ${timeoutMs} ms.`,
        httpStatus: 0,
      },
      { isTimeout: true }
    );
    this.name = "ApiTimeoutError";
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
  /** Override the default timeout for this call. */
  timeoutMs?: number;
}

function readEnvNumber(value: unknown, fallback: number, max: number): number {
  if (typeof value !== "string") return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, max);
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

function readTimeoutMs(): number {
  const env = (import.meta as unknown as { env?: Record<string, unknown> }).env;
  return readEnvNumber(env?.VITE_API_TIMEOUT_MS, DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS);
}

/**
 * Returns true only if the development fixture flag is set to the
 * exact string "enabled". Any other value, including the empty
 * string, an unrelated variable, or any case variation, returns
 * false. Fixtures are an explicit developer action; they are never
 * activated by API failure.
 */
export function readDevFixturesEnabled(): boolean {
  const env = (import.meta as unknown as { env?: Record<string, unknown> }).env;
  return env?.VITE_DEV_FIXTURES === DEV_FIXTURE_FLAG;
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

function combineSignals(
  external: AbortSignal | undefined,
  internal: AbortController
): AbortSignal {
  if (!external) return internal.signal;
  if (external.aborted) {
    internal.abort();
    return internal.signal;
  }
  const onExternalAbort = () => {
    internal.abort();
  };
  external.addEventListener("abort", onExternalAbort, { once: true });
  return internal.signal;
}

async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
  body?: unknown
): Promise<T> {
  const base = readBaseUrl();
  const url = buildUrl(base, path, options.query);
  const timeoutController = new AbortController();
  const timeoutMs = options.timeoutMs ?? readTimeoutMs();
  const timer = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  const signal = combineSignals(options.signal, timeoutController);
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
    signal,
    credentials: "omit",
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    window.clearTimeout(timer);
    if ((err as { name?: string })?.name === "AbortError") {
      if (options.signal?.aborted) {
        throw new ApiAbortError();
      }
      throw new ApiTimeoutError(timeoutMs);
    }
    throw new ApiClientError({
      code: "network_error",
      message: err instanceof Error ? err.message : "Network request failed.",
      httpStatus: 0,
    });
  }
  window.clearTimeout(timer);

  if (!response.ok) {
    throw new ApiClientError(await parseError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/**
 * Read a response as `text/plain` for downloads (exports).
 * Errors are mapped to the same envelope as JSON calls.
 */
async function requestText(
  path: string,
  options: RequestOptions = {}
): Promise<{ body: string; contentType: string; filename: string | null }> {
  const base = readBaseUrl();
  const url = buildUrl(base, path, options.query);
  const timeoutController = new AbortController();
  const timeoutMs = options.timeoutMs ?? readTimeoutMs();
  const timer = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  const signal = combineSignals(options.signal, timeoutController);
  const init: RequestInit = {
    method: "GET",
    headers: { Accept: "application/json, text/plain;q=0.9, */*;q=0.5" },
    signal,
    credentials: "omit",
  };
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    window.clearTimeout(timer);
    if ((err as { name?: string })?.name === "AbortError") {
      if (options.signal?.aborted) throw new ApiAbortError();
      throw new ApiTimeoutError(timeoutMs);
    }
    throw new ApiClientError({
      code: "network_error",
      message: err instanceof Error ? err.message : "Network request failed.",
      httpStatus: 0,
    });
  }
  window.clearTimeout(timer);
  if (!response.ok) {
    throw new ApiClientError(await parseError(response));
  }
  const contentDisposition = response.headers.get("content-disposition");
  const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
  return {
    body: await response.text(),
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
    filename: filenameMatch?.[1] ?? null,
  };
}

/**
 * Upload a single file as multipart/form-data. Used for archive
 * uploads. The file is passed as a Blob; the client never reads
 * its bytes into JavaScript memory beyond what the browser does
 * during fetch.
 */
async function requestUpload<T>(
  path: string,
  file: File | Blob,
  options: RequestOptions = {}
): Promise<T> {
  const base = readBaseUrl();
  const url = buildUrl(base, path, options.query);
  const timeoutController = new AbortController();
  const timeoutMs = options.timeoutMs ?? MAX_TIMEOUT_MS;
  const timer = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  const signal = combineSignals(options.signal, timeoutController);
  const form = new FormData();
  form.append("archive", file);
  const init: RequestInit = {
    method: "POST",
    headers: { Accept: "application/json" },
    signal,
    credentials: "omit",
    body: form,
  };
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    window.clearTimeout(timer);
    if ((err as { name?: string })?.name === "AbortError") {
      if (options.signal?.aborted) throw new ApiAbortError();
      throw new ApiTimeoutError(timeoutMs);
    }
    throw new ApiClientError({
      code: "network_error",
      message: err instanceof Error ? err.message : "Network request failed.",
      httpStatus: 0,
    });
  }
  window.clearTimeout(timer);
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
  getText(path: string, options?: RequestOptions) {
    return requestText(path, options);
  },
  upload<T>(path: string, file: File | Blob, options?: RequestOptions) {
    return requestUpload<T>(path, file, options);
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

/**
 * Map an unknown error to one of a small set of user-facing
 * categories. Used by error banners so the UI can pick an icon and
 * copy without parsing error text.
 */
export type ErrorCategory =
  | "cancelled"
  | "timeout"
  | "network"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "validation"
  | "rate_limited"
  | "provider_unavailable"
  | "duplicate"
  | "server"
  | "unknown";

export function categorizeError(err: unknown): ErrorCategory {
  if (err instanceof ApiAbortError) return "cancelled";
  if (err instanceof ApiTimeoutError) return "timeout";
  if (err instanceof ApiClientError) {
    const code = err.apiError.code;
    const status = err.apiError.httpStatus;
    if (code === "cancelled" || err.isAbort) return "cancelled";
    if (code === "timeout" || err.isTimeout) return "timeout";
    if (code === "network_error" || status === 0) return "network";
    if (code === "unauthorized" || status === 401) return "unauthorized";
    if (code === "forbidden" || status === 403) return "forbidden";
    if (code === "not_found" || status === 404) return "not_found";
    if (code === "validation_error" || status === 422) return "validation";
    if (code === "rate_limited" || status === 429) return "rate_limited";
    if (code === "duplicate" || status === 409) return "duplicate";
    if (code === "provider_unavailable" || status === 502 || status === 503) {
      return "provider_unavailable";
    }
    if (status >= 500) return "server";
    return "unknown";
  }
  return "unknown";
}
