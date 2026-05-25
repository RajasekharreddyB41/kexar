/**
 * ActiveModel.
 *
 * Hero piece of the control panel. Shows which model is currently
 * processing, its provider, the status of the call, and a failover
 * chain when the runtime has tried multiple providers.
 *
 * Status states:
 *   * healthy   - last LLM call succeeded.            emerald, solid.
 *   * calling   - call in flight, no success yet.     emerald, pulsing.
 *   * failing   - last call failed or just failed over. amber, pulsing.
 *   * exhausted - all providers down, run aborted.    rose, solid.
 *
 * Failover chain: ordered list of every model the runtime touched
 * during the current llm.call sequence. Each entry except the last
 * one rendered with a strike-through (it failed). The last entry is
 * the current/successful model. Hidden when chain has 0 or 1 entry.
 */

"use client";

export type ModelStatus = "healthy" | "calling" | "failing" | "exhausted";
export type Provider = "anthropic" | "openai" | "google" | "groq" | "unknown";

interface ActiveModelProps {
  model: string | null;
  status: ModelStatus;
  failoverChain: string[];
}

const STATUS_DOT: Record<ModelStatus, string> = {
  healthy: "bg-emerald-500",
  calling: "bg-emerald-400 animate-pulse",
  failing: "bg-amber-400 animate-pulse",
  exhausted: "bg-rose-500",
};

const PROVIDER_STYLES: Record<Provider, { label: string; chip: string }> = {
  anthropic: { label: "Anthropic", chip: "bg-amber-950 text-amber-300 ring-amber-900" },
  openai: { label: "OpenAI", chip: "bg-emerald-950 text-emerald-300 ring-emerald-900" },
  google: { label: "Google", chip: "bg-sky-950 text-sky-300 ring-sky-900" },
  groq: { label: "Groq", chip: "bg-rose-950 text-rose-300 ring-rose-900" },
  unknown: { label: "—", chip: "bg-zinc-800 text-zinc-400 ring-zinc-700" },
};

function detectProvider(model: string | null): Provider {
  if (!model) return "unknown";
  const m = model.toLowerCase();
  if (m.includes("claude")) return "anthropic";
  if (m.includes("gpt") || m.includes("o3") || m.includes("o4")) return "openai";
  if (m.includes("gemini")) return "google";
  if (m.includes("groq") || m.includes("llama") || m.includes("mixtral")) return "groq";
  return "unknown";
}

function displayName(model: string | null): string {
  if (!model) return "—";
  let m = model;
  if (m.startsWith("simulated-")) m = m.replace("simulated-", "");
  if (m.startsWith("groq/")) m = m.replace("groq/", "");
  if (m.includes("/")) m = m.split("/").slice(-1)[0] ?? m;
  return m;
}

export function ActiveModel({ model, status, failoverChain }: ActiveModelProps) {
  const provider = detectProvider(model);
  const providerStyle = PROVIDER_STYLES[provider];
  const dotClass = STATUS_DOT[status];
  const showChain = failoverChain.length > 1;

  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-widest text-zinc-500">Active model</div>
      <div className="flex items-center gap-2.5">
        <span className="relative inline-flex h-2 w-2 shrink-0">
          {status === "calling" && (
            <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-50 animate-ping" />
          )}
          {status === "failing" && (
            <span className="absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60 animate-ping" />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${dotClass}`} />
        </span>
        <span className="font-mono text-sm text-zinc-100 truncate">{displayName(model)}</span>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={`text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded ring-1 ${providerStyle.chip}`}
        >
          {providerStyle.label}
        </span>
        {model?.startsWith("simulated-") && (
          <span className="text-[10px] font-mono uppercase tracking-wide text-zinc-500 px-1.5 py-0.5 rounded bg-zinc-800/50 ring-1 ring-zinc-800">
            sim
          </span>
        )}
      </div>
      {showChain && (
        <div className="pt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] font-mono animate-in fade-in duration-300">
          {failoverChain.map((m, i) => {
            const isLast = i === failoverChain.length - 1;
            return (
              <span key={`${m}_${i}`} className="inline-flex items-center gap-1.5">
                <span
                  className={
                    isLast
                      ? "text-emerald-400"
                      : "text-zinc-500 line-through decoration-rose-400/60"
                  }
                >
                  {displayName(m)}
                </span>
                {!isLast && <span className="text-zinc-700">-&gt;</span>}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
