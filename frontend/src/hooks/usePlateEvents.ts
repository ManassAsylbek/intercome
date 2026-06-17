import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PLATE_LOG_KEY } from "./usePlates";

export interface PlateEvent {
  device_id: number;
  plate: string;
  matched: boolean;
  granted: boolean;
  action: string;
  owner: string | null;
  /** Client receive time — keys the banner so each event re-triggers it. */
  ts: number;
}

/**
 * Subscribes to the SSE stream for `plate_recognized` events (published by the
 * backend anpr_service). Exposes the latest event for the signalling banner
 * and invalidates the access-log query so the journal refreshes live.
 */
export function usePlateEvents() {
  const [event, setEvent] = useState<PlateEvent | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    const es = new EventSource(
      `/api/events/stream?token=${encodeURIComponent(token)}`,
    );

    es.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data) as {
          event: string;
          data: Record<string, unknown>;
        };
        if (payload.event === "plate_recognized") {
          setEvent({
            ...(payload.data as unknown as Omit<PlateEvent, "ts">),
            ts: Date.now(),
          });
          qc.invalidateQueries({ queryKey: PLATE_LOG_KEY });
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => es.close();

    return () => es.close();
  }, [qc]);

  return { event, clear: () => setEvent(null) };
}
