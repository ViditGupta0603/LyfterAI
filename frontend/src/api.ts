/** Thin client for the backend contract. Every failure becomes an ApiError with readable text. */

export type ResolutionSource = "LIVE_INFERENCE" | "LLM_CACHE";

export interface ChatMetadata {
  resolution_source: ResolutionSource;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id: string | null;
  fallback_attempts: number;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  metadata: ChatMetadata;
}

export interface Health {
  status: "ok";
  keys_configured: number;
  cache_enabled: boolean;
  model?: string;
  failure_simulation?: boolean;
}

const REQUEST_TIMEOUT_MS = 60_000; // backend gives up at ~45 s, so it answers first

export const API_URL: string = (
  window.__APP_CONFIG__?.API_URL ||
  import.meta.env.VITE_API_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn FastAPI's error shapes into one readable sentence. */
function describeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: string };
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
    const msg = (first.msg ?? "invalid input").replace(/^Value error, /, "");
    return field ? `${field}: ${msg}` : msg;
  }
  return null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, signal: controller.signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      throw new ApiError("The server took too long to answer. Please try again.", null);
    }
    throw new ApiError(`Couldn't reach the server at ${API_URL}. Is the backend running?`, null);
  } finally {
    clearTimeout(timer);
  }

  let body: unknown = null;
  const text = await res.text();
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null; // e.g. an HTML error page from a proxy
  }

  if (!res.ok) {
    const detail = describeDetail((body as { detail?: unknown } | null)?.detail);
    const fallback: Record<number, string> = {
      422: "The message was rejected as invalid.",
      502: "The model could not answer this request.",
      503: "All providers are unavailable right now.",
    };
    throw new ApiError(detail ?? fallback[res.status] ?? `Request failed (HTTP ${res.status}).`, res.status);
  }
  return body as T;
}

export function sendChat(args: {
  sessionId: string;
  message: string;
  systemPrompt?: string;
  simulateFailure?: string;
}): Promise<ChatResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (args.simulateFailure) headers["X-Simulate-Failure"] = args.simulateFailure;
  const payload: Record<string, string> = { session_id: args.sessionId, message: args.message };
  if (args.systemPrompt && args.systemPrompt.trim()) payload.system_prompt = args.systemPrompt;
  return request<ChatResponse>("/chat", { method: "POST", headers, body: JSON.stringify(payload) });
}

export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}
