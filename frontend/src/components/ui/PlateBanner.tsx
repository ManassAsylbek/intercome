import { useEffect } from "react";
import { Car, CheckCircle2, XCircle, X } from "lucide-react";
import type { PlateEvent } from "@/hooks/usePlateEvents";

/**
 * Звуковой сигнал распознавания: короткий приятный тон при разрешении,
 * длинный низкий «зуммер» при отказе. Web Audio — без аудиофайлов.
 */
function beep(granted: boolean) {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = granted ? "sine" : "square";
    osc.frequency.value = granted ? 880 : 200;
    gain.gain.setValueAtTime(0.18, ctx.currentTime);
    const dur = granted ? 0.25 : 0.7;
    osc.start();
    osc.stop(ctx.currentTime + dur);
    osc.onended = () => ctx.close();
  } catch {
    // audio unavailable — colour signalling still works
  }
}

/** Цветовая + звуковая сигнализация распознавания номера авто. */
export function PlateBanner({
  event,
  onDismiss,
}: {
  event: PlateEvent;
  onDismiss: () => void;
}) {
  // Re-runs per event (ts changes): beep + auto-dismiss after 6s.
  useEffect(() => {
    beep(event.granted);
    const timer = setTimeout(onDismiss, 6000);
    return () => clearTimeout(timer);
  }, [event.ts, event.granted, onDismiss]);

  const granted = event.granted;
  const Icon = granted ? CheckCircle2 : XCircle;

  return (
    <div
      className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 w-96 rounded-xl shadow-xl border overflow-hidden ${
        granted
          ? "bg-green-50 border-green-300"
          : "bg-red-50 border-red-300"
      }`}
    >
      <div
        className={`h-1.5 ${granted ? "bg-green-500" : "bg-red-500"}`}
        aria-hidden
      />
      <div className="flex items-start gap-3 px-4 py-3">
        <div
          className={`flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center ${
            granted ? "bg-green-100" : "bg-red-100"
          }`}
        >
          <Icon
            className={`w-5 h-5 ${
              granted ? "text-green-600" : "text-red-600"
            }`}
          />
        </div>

        <div className="flex-1 min-w-0">
          <p
            className={`text-sm font-semibold ${
              granted ? "text-green-800" : "text-red-800"
            }`}
          >
            {granted ? "Проезд разрешён" : "Проезд запрещён"}
          </p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Car className="w-3.5 h-3.5 text-gray-400" />
            <code className="text-xs font-mono font-semibold text-gray-700">
              {event.plate}
            </code>
          </div>
          {event.owner && (
            <p className="text-xs text-gray-500 mt-0.5 truncate">
              {event.owner}
            </p>
          )}
          {event.action === "open_failed" && (
            <p className="text-xs text-red-600 mt-0.5">
              Не удалось открыть шлагбаум
            </p>
          )}
        </div>

        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-gray-600 flex-shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
