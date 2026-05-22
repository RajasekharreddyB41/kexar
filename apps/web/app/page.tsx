export default function HomePage() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center px-6">
      <div className="max-w-xl space-y-6">
        <div className="flex items-center gap-3">
          <div aria-hidden className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs uppercase tracking-widest text-zinc-400">Build in progress</span>
        </div>
        <h1 className="text-5xl font-semibold tracking-tight">Kexar</h1>
        <p className="text-lg text-zinc-400 leading-relaxed">The resilience runtime for production AI agents. Demo lands May 28, 2026.</p>
        <p className="text-sm text-zinc-500">TrueFoundry Resilient Agents track</p>
      </div>
    </main>
  );
}
