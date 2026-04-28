import { useEffect, useState } from "react";

export interface ActiveCall {
  caller: string;
  callee: string;
  started_at: string;
  call_id: string;
  video_src?: string; // go2rtc stream name, e.g. "panel-1"
}

export function useCallEvents() {
  const [activeCall, setActiveCall] = useState<ActiveCall | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    const url = `/api/events/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data) as {
          event: string;
          data: Record<string, unknown>;
        };
        if (payload.event === "call_started") {
          setActiveCall(payload.data as unknown as ActiveCall);
        } else if (payload.event === "call_ended" || payload.event === "idle") {
          setActiveCall(null);
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, []);

  return { activeCall };
}
