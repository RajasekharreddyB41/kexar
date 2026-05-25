/**
 * API client for the Kexar backend.
 *
 * Three calls:
 *   startRun(message, incidentId?)     POST /api/runs
 *   toggleChaos(tool, killed)          POST /api/demo/chaos
 *   getEventStreamUrl(runId)           url builder for the SSE endpoint
 *
 * Returns a discriminated { ok: true, data } | { ok: false, error } union.
 * Components handle the union in render logic - no throws here.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://kexar-api.onrender.com");

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export interface StartRunResponse {
  run_id: string;
  status: string;
}

export interface ChaosToggleResponse {
  tool: string;
  killed: boolean;
  currently_killed: string[];
}

async function postJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const detail = await response
        .json()
        .then((b) => (typeof b?.detail === "string" ? b.detail : ""))
        .catch(() => "");
      return {
        ok: false,
        error: `HTTP ${response.status}${detail ? `: ${detail}` : ""}`,
      };
    }

    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return { ok: false, error: `network: ${message}` };
  }
}

export async function startRun(
  message: string,
  incidentId: string = "inc_checkout_latency"
): Promise<ApiResult<StartRunResponse>> {
  return postJson<StartRunResponse>("/api/runs", {
    user_message: message,
    incident_id: incidentId,
  });
}

export async function toggleChaos(
  tool: string,
  killed: boolean
): Promise<ApiResult<ChaosToggleResponse>> {
  return postJson<ChaosToggleResponse>("/api/demo/chaos", {
    tool,
    killed,
  });
}

export function getEventStreamUrl(runId: string): string {
  return `${API_BASE}/api/runs/${runId}/events`;
}

export function getApiBase(): string {
  return API_BASE;
}
