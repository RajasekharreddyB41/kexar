/**
 * Kexar landing page.
 *
 * One screen, no scroll required on a laptop for the hero beat.
 * Headline, subhead, two CTAs, three-column differentiator row,
 * the market-scan positioning line, small footer.
 *
 * Visual language matches the IR page: bg-zinc-950, emerald accent,
 * lucide icons, shadcn Button.
 */

import Link from "next/link";
import {
  ArrowRight,
  Network,
  Wrench,
  Radio,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const REPO_URL = "https://github.com/RajasekharreddyB41/kexar";

// Inline GitHub mark. lucide-react dropped brand icons, and pulling
// a separate icon package for one logo is not worth it.
function GithubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      className={className}
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.09 3.29 9.41 7.86 10.94.58.11.79-.25.79-.55v-2.05c-3.2.7-3.87-1.36-3.87-1.36-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.67 1.25 3.32.96.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.7 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .97-.31 3.18 1.18a11.05 11.05 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.12 3.04.74.81 1.18 1.84 1.18 3.1 0 4.43-2.69 5.41-5.26 5.69.41.36.78 1.07.78 2.16v3.2c0 .31.21.67.8.55C20.22 21.4 23.5 17.09 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}

export default function HomePage() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      <Header />
      <Hero />
      <Benefits />
      <Differentiator />
      <Footer />
    </main>
  );
}

function Header() {
  return (
    <header className="flex items-center justify-between px-8 py-5 border-b border-zinc-900">
      <div className="flex items-center">
        <span className="font-semibold tracking-wider text-sm">KEXAR</span>
      </div>
      <nav className="flex items-center gap-2 text-sm">
        <Link
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-zinc-300 hover:text-zinc-100 hover:bg-zinc-900 transition"
        >
          <GithubIcon className="h-3.5 w-3.5" />
          GitHub
        </Link>
        <Link
          href="/ir"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition border border-emerald-500/20"
        >
          IR demo
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </nav>
    </header>
  );
}

function Hero() {
  return (
    <section className="flex-1 flex items-start justify-center px-8 pt-20 pb-24">  {/* TUNED_v2 */}
      <div className="max-w-3xl text-center space-y-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-xs text-zinc-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          TrueFoundry Resilient Agents track, May 2026
        </div>

        <h1 className="text-5xl md:text-6xl font-semibold tracking-tight leading-tight">
          The resilience runtime <br />
          <span className="text-emerald-400">for AI agents.</span>
        </h1>

        <p className="text-lg md:text-xl text-zinc-400 leading-relaxed max-w-2xl mx-auto">
          Sits on top of your LLM gateway. Wraps every tool call. Makes graceful
          degradation a primitive instead of a project you write from scratch.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
          <Button
            asChild
            size="lg"
            className="bg-emerald-400 hover:bg-emerald-300 text-zinc-950 font-semibold shadow-lg shadow-emerald-500/20"
          >
            <Link href="/ir">
              Try the IR demo
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Link>
          </Button>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="bg-transparent border-zinc-700 text-zinc-200 hover:bg-zinc-900 hover:text-zinc-100"
          >
            <Link href={REPO_URL} target="_blank" rel="noreferrer">
              <GithubIcon className="h-4 w-4 mr-1.5" />
              View on GitHub
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

function Benefits() {
  const items = [
    {
      icon: Network,
      title: "Multi-provider failover",
      body: "Routes through TrueFoundry Gateway with a cascade across Claude, GPT-4o, Gemini, and Groq. When one provider rate-limits or browns out, the next one picks up mid-run.",
    },
    {
      icon: Wrench,
      title: "Tools that degrade",
      body: "Every MCP tool call has a timeout, retry, and circuit breaker. When a tool dies, the agent does not crash. It tells the user what is unavailable and reasons over what is left.",
    },
    {
      icon: Radio,
      title: "Failures are events",
      body: "Every retry, failover, and circuit-open is a typed event on a bus. The control panel renders them live. Resilience is visible to the user, not buried in logs.",
    },
  ];

  return (
    <section className="px-8 py-16 border-t border-zinc-900">
      <div className="max-w-6xl mx-auto grid md:grid-cols-3 gap-6">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.title}
              className="p-6 rounded-xl bg-zinc-900/40 border border-zinc-800/60 hover:border-zinc-700 transition"
            >
              <div className="h-9 w-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-4">
                <Icon className="h-4 w-4 text-emerald-400" />
              </div>
              <h3 className="text-base font-semibold mb-2 tracking-tight">
                {item.title}
              </h3>
              <p className="text-sm text-zinc-400 leading-relaxed">
                {item.body}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Differentiator() {
  return (
    <section className="px-8 py-20 border-t border-zinc-900">
      <div className="max-w-3xl mx-auto text-center space-y-6">
        <p className="text-xs uppercase tracking-widest text-zinc-500">
          The gap nobody is filling
        </p>
        <p className="text-2xl md:text-3xl font-medium leading-relaxed">
          <span className="text-zinc-500">Gateways route. Frameworks orchestrate. Observability watches.</span>{" "}
          <span className="text-zinc-100">
            Kexar owns what your agent does when all of that runs out.
          </span>
        </p>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="px-8 py-6 border-t border-zinc-900 text-xs text-zinc-500 flex flex-wrap items-center justify-between gap-3">
      <div>
        Built on TrueFoundry AI Gateway. Hackathon submission, May 2026.
      </div>
      <Link
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        className="hover:text-zinc-300 transition"
      >
        github.com/RajasekharreddyB41/kexar
      </Link>
    </footer>
  );
}
