import { useState } from "react";
import { DoorOpen, PhoneIncoming, Phone, PhoneOff, X } from "lucide-react";
import { apiClient } from "@/api/client";
import type { ActiveCall } from "@/hooks/useCallEvents";
import type { SIPCallState } from "@/hooks/useSIPClient";
import { WebRTCPlayer } from "./WebRTCPlayer";

interface Props {
  call: ActiveCall | null;
  sipState: SIPCallState;
  onDismiss: () => void;
  onAnswer: () => void;
  onHangup: () => void;
}

export function CallBanner({
  call,
  sipState,
  onDismiss,
  onAnswer,
  onHangup,
}: Props) {
  const [unlocking, setUnlocking] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUnlock = async () => {
    setUnlocking(true);
    setError(null);
    try {
      await apiClient.post("/calls/unlock");
      setUnlocked(true);
    } catch {
      setError("Failed to unlock");
    } finally {
      setUnlocking(false);
    }
  };

  const isActive = sipState === "active";
  const isRinging = sipState === "ringing";

  return (
    <div className="fixed top-4 right-4 z-50 bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden w-96">
      {/* Live video */}
      <WebRTCPlayer src={call?.video_src ?? "panel-2"} />

      {/* Controls */}
      <div className="flex items-start gap-3 px-4 py-3">
        {/* Icon */}
        <div className="flex-shrink-0 w-9 h-9 bg-indigo-100 rounded-full flex items-center justify-center">
          <PhoneIncoming className="w-4 h-4 text-indigo-600 animate-pulse" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">
            {isActive ? "Звонок активен" : "Звонок с двери"}
          </p>
          {call && (
            <>
              <p className="text-xs text-gray-500">
                From: {call.caller} &rarr; {call.callee}
              </p>
              <p className="text-xs text-gray-400">
                {new Date(call.started_at).toLocaleTimeString()}
              </p>
            </>
          )}

          {error && (
            <p className="text-xs text-red-500 mt-1">Ошибка открытия</p>
          )}

          {/* SIP + Door controls */}
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {!isActive && (
              <button
                onClick={onAnswer}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-700 transition-colors"
              >
                <Phone className="w-3.5 h-3.5" />
                {isRinging ? "Ответить" : "Говорить"}
              </button>
            )}

            {isActive && (
              <button
                onClick={onHangup}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 text-white hover:bg-red-700 transition-colors"
              >
                <PhoneOff className="w-3.5 h-3.5" />
                Сбросить
              </button>
            )}

            <button
              onClick={handleUnlock}
              disabled={unlocking || unlocked}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-60 transition-colors"
            >
              <DoorOpen className="w-3.5 h-3.5" />
              {unlocked
                ? "Открыто!"
                : unlocking
                  ? "Открывается…"
                  : "Открыть дверь"}
            </button>
          </div>
        </div>

        {/* Dismiss */}
        <button
          onClick={() => {
            onHangup();
            onDismiss();
          }}
          className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors mt-0.5"
          title="Закрыть"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
