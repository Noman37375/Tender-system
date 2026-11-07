"use client";
// Live run events over Server-Sent Events (PRD §10.5, D10).
//
// - EventSource cannot send headers, so the access token goes in `?access_token=`.
// - While the stream is merely interrupted, EventSource reconnects by itself and sends
//   `Last-Event-ID` natively; the server replays missed rows from run_events.
// - If the browser gives up (readyState CLOSED, e.g. a 401 after the token expired), we refresh
//   the token and reconnect manually, passing the last id as `?last_event_id=` because a new
//   EventSource cannot set the header.
// - After repeated failures we report `polling`; callers then poll GET /runs/{id} every 5 s.
//   We keep trying SSE in the background every 30 s.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, refreshAccess } from "./api";
import { SSE_EVENT_TYPES, type RunEvent, type SseEventType } from "./types";

export type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "polling" | "closed";

const MAX_MANUAL_RETRIES = 3;
const MAX_NATIVE_ERRORS = 5;
const SSE_RETRY_WHILE_POLLING_MS = 30_000;
const MAX_EVENTS = 500;

interface Handlers {
  onEvent: (e: RunEvent) => void;
  onState: (s: StreamState) => void;
}

export class RunEventStream {
  private es: EventSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private manualFailures = 0;
  private nativeErrors = 0;
  private stopped = false;

  constructor(
    private runId: string,
    private handlers: Handlers,
    public lastEventId: string | null = null,
  ) {}

  start() {
    this.stopped = false;
    this.open("connecting");
  }

  stop() {
    this.stopped = true;
    this.clearTimer();
    this.es?.close();
    this.es = null;
    this.handlers.onState("closed");
  }

  /** Drop the current connection and open a fresh one now (e.g. a "Reconnect" button). */
  reconnect() {
    this.manualFailures = 0;
    this.clearTimer();
    this.es?.close();
    this.es = null;
    this.stopped = false;
    void refreshAccess().finally(() => this.open("connecting"));
  }

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private open(state: StreamState) {
    if (this.stopped || typeof window === "undefined" || !("EventSource" in window)) {
      if (!this.stopped) this.handlers.onState("polling");
      return;
    }
    this.handlers.onState(state);
    const es = new EventSource(api.runEventsUrl(this.runId, this.lastEventId));
    this.es = es;

    es.onopen = () => {
      this.manualFailures = 0;
      this.nativeErrors = 0;
      this.handlers.onState("live");
    };

    for (const type of SSE_EVENT_TYPES) {
      es.addEventListener(type, (ev) => this.dispatch(type, ev as MessageEvent<string>));
    }

    es.onerror = () => {
      if (this.stopped || this.es !== es) return;
      if (es.readyState === EventSource.CONNECTING && ++this.nativeErrors < MAX_NATIVE_ERRORS) {
        // Native auto-reconnect is in progress and will send Last-Event-ID itself.
        this.handlers.onState("reconnecting");
        return;
      }
      es.close();
      this.es = null;
      this.nativeErrors = 0;
      this.manualFailures += 1;
      if (this.manualFailures <= MAX_MANUAL_RETRIES) {
        this.handlers.onState("reconnecting");
        const delay = 1000 * 2 ** (this.manualFailures - 1);
        this.timer = setTimeout(() => {
          void refreshAccess().finally(() => this.open("reconnecting"));
        }, delay);
      } else {
        this.handlers.onState("polling");
        this.timer = setTimeout(() => {
          this.manualFailures = MAX_MANUAL_RETRIES; // one more try, then back to polling
          void refreshAccess().finally(() => this.open("polling"));
        }, SSE_RETRY_WHILE_POLLING_MS);
      }
    };
  }

  private dispatch(type: SseEventType, ev: MessageEvent<string>) {
    if (ev.lastEventId) this.lastEventId = ev.lastEventId;
    let data: Partial<Omit<RunEvent, "id" | "type">> = {};
    try {
      data = JSON.parse(ev.data);
    } catch {
      return; // malformed frame; ignore
    }
    this.handlers.onEvent({
      id: ev.lastEventId || null,
      type,
      run_id: data.run_id ?? this.runId,
      node: data.node ?? null,
      ts: data.ts ?? new Date().toISOString(),
      payload: (data.payload ?? {}) as never,
    } as RunEvent);
  }
}

/**
 * React hook around RunEventStream. `enabled=false` closes the stream (e.g. run finished);
 * re-enabling resumes from the last seen event id.
 */
export function useRunEvents(
  runId: string | null | undefined,
  enabled: boolean,
  onEvent?: (e: RunEvent) => void,
) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<StreamState>("idle");
  const streamRef = useRef<RunEventStream | null>(null);
  const lastIdRef = useRef<string | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  // A different run starts with a clean log (declared first so it runs before the stream opens).
  useEffect(() => {
    seen.current = new Set();
    lastIdRef.current = null;
    setEvents([]);
  }, [runId]);

  useEffect(() => {
    if (!runId || !enabled) return;
    const stream = new RunEventStream(
      runId,
      {
        onState: setState,
        onEvent: (e) => {
          if (e.id) {
            if (seen.current.has(e.id)) return; // replay duplicate
            seen.current.add(e.id);
            lastIdRef.current = e.id;
          }
          setEvents((prev) => {
            const next = [...prev, e];
            return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
          });
          onEventRef.current?.(e);
        },
      },
      lastIdRef.current,
    );
    streamRef.current = stream;
    stream.start();
    return () => {
      stream.stop();
      streamRef.current = null;
    };
  }, [runId, enabled]);

  const reconnect = useCallback(() => streamRef.current?.reconnect(), []);

  return { events, state: enabled ? state : "closed", reconnect } as const;
}
