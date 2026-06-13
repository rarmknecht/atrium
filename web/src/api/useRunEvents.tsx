import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState } from "react";

import type { RunEvent } from "./types";

interface RunEventsState {
  connected: boolean;
  recent: RunEvent[];
  /** module_ids currently executing */
  running: Set<string>;
}

const Ctx = createContext<RunEventsState>({
  connected: false,
  recent: [],
  running: new Set(),
});

export const useRunEvents = () => useContext(Ctx);

/** Single shared WebSocket to /ws — keeps caches fresh and tracks in-flight runs. */
export function RunEventsProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [recent, setRecent] = useState<RunEvent[]>([]);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stop = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (stop) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const token = localStorage.getItem("atrium-token");
      const qs = token ? `?token=${encodeURIComponent(token)}` : "";
      const ws = new WebSocket(`${proto}://${location.host}/ws${qs}`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stop) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (msg) => {
        const event: RunEvent = JSON.parse(msg.data);
        if (event.type === "hello") return;
        setRecent((r) => [event, ...r].slice(0, 50));
        if (event.module_id) {
          setRunning((prev) => {
            const next = new Set(prev);
            if (event.type === "run.started") next.add(event.module_id!);
            else next.delete(event.module_id!);
            return next;
          });
        }
        // refresh anything a run could have changed
        qc.invalidateQueries({ queryKey: ["runs"] });
        if (event.type === "run.finished") {
          qc.invalidateQueries({ queryKey: ["reports"] });
          qc.invalidateQueries({ queryKey: ["modules"] });
        }
      };
    };

    connect();
    return () => {
      stop = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [qc]);

  return <Ctx.Provider value={{ connected, recent, running }}>{children}</Ctx.Provider>;
}
