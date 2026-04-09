import { useState, useEffect, useRef, useCallback } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useCallEvents } from "@/hooks/useCallEvents";
import { useSIPClient, type SIPCallState } from "@/hooks/useSIPClient";
import { CallBanner } from "@/components/ui/CallBanner";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Monitor,
  GitFork,
  Settings,
  LogOut,
  Radio,
} from "lucide-react";

const navItems = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/devices", icon: Monitor, label: "Devices" },
  { to: "/routing", icon: GitFork, label: "Routing Rules" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const { activeCall } = useCallEvents();
  const [dismissed, setDismissed] = useState(false);
  const [sipState, setSipState] = useState<SIPCallState>("idle");
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement>(null);

  const { answer: sipAnswer, hangup } = useSIPClient({
    onStateChange: setSipState,
    onRemoteStream: setRemoteStream,
  });

  // Whenever remote stream arrives (even late), assign to audio and play
  useEffect(() => {
    const el = remoteAudioRef.current;
    if (!el || !remoteStream) return;
    console.log(
      "[audio] Got remote stream, tracks:",
      remoteStream.getTracks().map((t) => `${t.kind}:${t.readyState}`),
    );
    el.srcObject = remoteStream;
    el.muted = false;
    el.volume = 1.0;
    el.play()
      .then(() => console.log("[audio] Playing remote stream OK"))
      .catch((e) => console.error("[audio] play error:", e));
  }, [remoteStream]);

  // Stop audio on call end
  useEffect(() => {
    if (sipState === "idle" || sipState === "ended") {
      const el = remoteAudioRef.current;
      if (el) {
        el.pause();
        el.srcObject = null;
      }
      setRemoteStream(null);
    }
  }, [sipState]);

  // answer() runs inside user gesture — browser will allow play()
  const answer = useCallback(() => {
    sipAnswer();
  }, [sipAnswer]);

  // Reset dismiss state when a new call comes in
  useEffect(() => {
    if (activeCall) setDismissed(false);
  }, [activeCall?.call_id]);

  const showBanner =
    (activeCall && !dismissed) ||
    sipState === "ringing" ||
    sipState === "active";

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Hidden audio element for SIP remote audio */}
      <audio
        ref={remoteAudioRef}
        autoPlay
        muted={false}
        style={{ display: "none" }}
      />

      {/* Sidebar */}
      <aside className="w-60 bg-gray-900 flex flex-col">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center">
              <Radio className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-white font-semibold text-sm leading-tight">
                Intercom
              </p>
              <p className="text-gray-400 text-xs">Management Server</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                  isActive
                    ? "bg-indigo-600 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800",
                )
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User */}
        <div className="px-3 py-4 border-t border-gray-800">
          <div className="flex items-center justify-between px-2">
            <div>
              <p className="text-white text-sm font-medium">{user?.username}</p>
              <p className="text-gray-500 text-xs">{user?.email}</p>
            </div>
            <button
              onClick={logout}
              className="text-gray-400 hover:text-white transition-colors p-1.5 rounded-md hover:bg-gray-800"
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Call notification banner — show when SSE call OR SIP ringing/active */}
      {showBanner && (
        <CallBanner
          call={activeCall ?? null}
          sipState={sipState}
          onDismiss={() => setDismissed(true)}
          onAnswer={answer}
          onHangup={hangup}
        />
      )}
    </div>
  );
}
