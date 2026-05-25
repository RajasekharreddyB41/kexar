/**
 * SSE client for the Kexar event stream.
 *
 * Wraps the browser's EventSource in a React hook. Subscribes to one
 * runs event stream, parses every message into a typed KexarEvent,
 * invokes onEvent. Closes the connection on terminal events
 * (run.complete / run.aborted) or on component unmount.
 *
 * Why this exists separately from lib/api.ts:
 *   * api.ts is plain functions, callable anywhere.
 *   * SSE has a lifecycle tied to a component (open / close / cleanup).
 *     The hook is the right abstraction.
 *
 * Usage:
 *   useEventStream(runId, (event) => {
 *     dispatch({ type: "event", event });
 *   });
 */

"use client";

import { useEffect, useRef } from "react";

import { getEventStreamUrl } from "@/lib/api";
import { isTerminal, type KexarEvent } from "@/lib/events";

type EventHandler = (event: KexarEvent) => void;

interface UseEventStreamOptions {
  onError?: (error: Event) => void;
  onClose?: () => void;
}

/**
 * Subscribe to the SSE event stream for a run.
 *
 * Pass null to skip the subscription (e.g. before a run has started).
 * Changing runId tears down the old connection and opens a new one.
 */
export function useEventStream(
  runId: string | null,
  onEvent: EventHandler,
  options: UseEventStreamOptions = {}
): void {
  // Stash the callbacks in refs so we do not tear down the connection
  // every time the parent component re-renders. EventSource is expensive
  // to recreate and we want stability across re-renders.
  const onEventRef = useRef<EventHandler>(onEvent);
  const onErrorRef = useRef<UseEventStreamOptions["onError"]>(options.onError);
  const onCloseRef = useRef<UseEventStreamOptions["onClose"]>(options.onClose);

  useEffect(() => {
    onEventRef.current = onEvent;
    onErrorRef.current = options.onError;
    onCloseRef.current = options.onClose;
  });

  useEffect(() => {
    if (!runId) {
      return;
    }

    const url = getEventStreamUrl(runId);
    const source = new EventSource(url);

    // The backend uses sse-starlette which sets per-event "event:" lines.
    // EventSource only invokes onmessage for events WITHOUT a type, so we
    // attach generic listeners. We could enumerate all 17 KexarEventType
    // values but listening to "message" plus a few named ones is fragile.
    // Cleaner: parse every incoming message via the raw "message" handler
    // by listening to all named event types we know about.
    //
    // Easiest correct path: register one listener per known event type
    // string, plus a fallback on "message" for any we missed. Or, since
    // sse-starlette puts the same JSON in `data` regardless of the
    // `event:` field, we can pull it from the underlying event.

    const handle = (raw: MessageEvent) => {
      try {
        const event = JSON.parse(raw.data) as KexarEvent;
        onEventRef.current(event);
        if (isTerminal(event)) {
          source.close();
          onCloseRef.current?.();
        }
      } catch (err) {
        // Malformed event. Skip rather than tear down the whole stream.
        // Production system would surface this somewhere.
        // eslint-disable-next-line no-console
        console.warn("kexar: failed to parse SSE event", err, raw.data);
      }
    };

    // Listen to every event type we know about. EventSource needs an
    // explicit addEventListener for each named event type since the
    // backend sends "event: llm.failover" not just default messages.
    const eventTypes = [
      "step.start",
      "step.end",
      "llm.call.start",
      "llm.call.success",
      "llm.call.failure",
      "llm.failover",
      "tool.call.start",
      "tool.call.success",
      "tool.call.failure",
      "tool.circuit_open",
      "tool.circuit_close",
      "degrade.entered",
      "degrade.exited",
      "budget.warn",
      "budget.exceeded",
      "run.start",
      "run.complete",
      "run.aborted",
    ];

    for (const type of eventTypes) {
      source.addEventListener(type, handle);
    }

    // Fallback for any event missing a named type field.
    source.onmessage = handle;

    source.onerror = (e) => {
      // EventSource auto-reconnects on transient failures. Only invoke
      // onError if the connection closes for real. Browsers expose this
      // via readyState === EventSource.CLOSED.
      if (source.readyState === EventSource.CLOSED) {
        onErrorRef.current?.(e);
        onCloseRef.current?.();
      }
    };

    return () => {
      source.close();
    };
  }, [runId]);
}
