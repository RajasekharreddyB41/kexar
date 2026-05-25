/**
 * Fixtures loader.
 *
 * Static event-stream snapshots captured from real runs. Used as
 * a fallback for the demo if the live backend is unreachable, and
 * for the Replay feature during the recording (Day 7).
 *
 * Each fixture has the same shape:
 *   { name: string, events: KexarEvent[] }
 *
 * To re-capture, see scripts/capture-fixtures.sh in the repo root
 * or the Day 6 commit message that introduced this directory.
 */

import deepChaosFixture from "./deep_chaos.json";
import happyFixture from "./happy.json";
import killMetricsFixture from "./kill_metrics.json";
import type { KexarEvent } from "@/lib/events";

export interface Fixture {
  name: string;
  label: string;
  description: string;
  events: KexarEvent[];
}

const happy: Fixture = {
  name: "happy",
  label: "Happy path",
  description: "All tools healthy. Agent solves the incident through the full cascade.",
  events: (happyFixture as { events: KexarEvent[] }).events,
};

const killMetrics: Fixture = {
  name: "kill_metrics",
  label: "Metrics down",
  description: "fetch_metrics is killed. Agent recovers via logs and runbook.",
  events: (killMetricsFixture as { events: KexarEvent[] }).events,
};

const deepChaos: Fixture = {
  name: "deep_chaos",
  label: "Deep chaos",
  description:
    "Both metrics and logs are killed. Agent reasons from runbook alone.",
  events: (deepChaosFixture as { events: KexarEvent[] }).events,
};

export const FIXTURES: Record<string, Fixture> = {
  happy,
  kill_metrics: killMetrics,
  deep_chaos: deepChaos,
};

export function getFixture(name: string): Fixture | null {
  return FIXTURES[name] ?? null;
}

export function listFixtures(): Fixture[] {
  return Object.values(FIXTURES);
}
