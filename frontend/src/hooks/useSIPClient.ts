import { useEffect, useRef, useCallback } from "react";
import JsSIP from "jssip";
import type { RTCSession } from "jssip/lib/RTCSession";

export type SIPCallState = "idle" | "ringing" | "active" | "ended";

interface SIPClientOptions {
  onStateChange?: (state: SIPCallState) => void;
  onRemoteStream?: (stream: MediaStream) => void;
}

const SIP_USER = "1099";
const SIP_PASSWORD = "BrowserSip1099";

export function useSIPClient({
  onStateChange,
  onRemoteStream,
}: SIPClientOptions = {}) {
  const sessionRef = useRef<RTCSession | null>(null);

  // Refs so callbacks never cause UA restart
  const onStateChangeRef = useRef(onStateChange);
  const onRemoteStreamRef = useRef(onRemoteStream);
  onStateChangeRef.current = onStateChange;
  onRemoteStreamRef.current = onRemoteStream;

  const setState = useCallback((s: SIPCallState) => {
    onStateChangeRef.current?.(s);
  }, []);

  useEffect(() => {
    const isSecure = window.location.protocol === "https:";
    const wsUrl = `${isSecure ? "wss" : "ws"}://${window.location.host}/sip`;
    const socket = new JsSIP.WebSocketInterface(wsUrl);

    const ua = new JsSIP.UA({
      sockets: [socket],
      uri: `sip:${SIP_USER}@${window.location.hostname}`,
      password: SIP_PASSWORD,
      register: true,
      session_timers: false,
    });

    ua.on("newRTCSession", ({ session }: { session: RTCSession }) => {
      if (session.direction !== "incoming") return;

      sessionRef.current = session;
      setState("ringing");
      console.log(
        "[SIP] Incoming call from",
        session.remote_identity?.uri?.user,
      );

      // Subscribe to peerconnection BEFORE answer() — it fires during answer()
      session.on(
        "peerconnection",
        ({ peerconnection }: { peerconnection: RTCPeerConnection }) => {
          console.log(
            "[SIP] peerconnection created, signalingState:",
            peerconnection.signalingState,
          );

          peerconnection.addEventListener("track", (e) => {
            console.log(
              "[SIP] track event kind:",
              e.track.kind,
              "streams:",
              e.streams.length,
            );
            // e.streams[0] may be undefined in some browsers — create MediaStream from track
            const stream = e.streams[0] ?? new MediaStream([e.track]);
            // Workaround for some browsers not attaching track to DOM correctly for AEC
            onRemoteStreamRef.current?.(stream);
          });

          // Fallback: iceconnectionstate change — try to grab stream after ICE connects
          peerconnection.addEventListener("iceconnectionstatechange", () => {
            const state = peerconnection.iceConnectionState;
            console.log("[SIP] ICE state:", state);
            if (state === "connected" || state === "completed") {
              const receivers = peerconnection.getReceivers();
              const audioTracks = receivers
                .map((r) => r.track)
                .filter((t) => t.readyState === "live");
              if (audioTracks.length > 0) {
                console.log(
                  "[SIP] ICE connected, delivering",
                  audioTracks.length,
                  "audio tracks via fallback",
                );
                onRemoteStreamRef.current?.(new MediaStream(audioTracks));
              }
            }
          });
        },
      );

      session.on("accepted", () => {
        setState("active");
        console.log("[SIP] Call accepted/active");
      });

      session.on("ended", () => {
        sessionRef.current = null;
        setState("ended");
        setTimeout(() => setState("idle"), 2000);
        console.log("[SIP] Call ended");
      });

      session.on("failed", ({ cause }: { cause: string }) => {
        sessionRef.current = null;
        setState("idle");
        console.warn("[SIP] Call failed:", cause);
      });
    });

    ua.on("registered", () => console.log("[SIP] Registered as", SIP_USER));
    ua.on("registrationFailed", (e: unknown) =>
      console.error("[SIP] Registration failed:", e),
    );
    ua.on("connected", () => console.log("[SIP] WebSocket connected"));
    ua.on("disconnected", () => console.warn("[SIP] WebSocket disconnected"));

    ua.start();

    return () => {
      sessionRef.current?.terminate?.();
      sessionRef.current = null;
      ua.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const answer = useCallback(() => {
    const session = sessionRef.current;
    if (!session) {
      console.warn("[SIP] answer() — no active session");
      return;
    }
    console.log("[SIP] Answering...");
    try {
      // Use local STUN so browser emits srflx candidates with real LAN IP.
      // Without STUN, HTTPS pages produce mDNS (*.local) host candidates
      // that Asterisk cannot resolve → ICE fails → immediate call drop.
      const stunUrl = `stun:${window.location.hostname}:3478`;
      session.answer({
        mediaConstraints: {
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        },
        pcConfig: { iceServers: [{ urls: stunUrl }] },
      });
    } catch (err) {
      console.error("[SIP] answer() error:", err);
    }
  }, []);

  const hangup = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;
    try {
      session.terminate();
    } catch {
      // already terminated
    }
    sessionRef.current = null;
    setState("idle");
  }, [setState]);

  return { answer, hangup };
}
