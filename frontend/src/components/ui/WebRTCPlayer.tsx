import { useEffect, useRef, useState } from "react";

interface Props {
  /** go2rtc stream name, e.g. "door" */
  src: string;
}

export function WebRTCPlayer({ src }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pc = new RTCPeerConnection({ bundlePolicy: "max-bundle" });

    pc.ontrack = ({ streams }) => {
      if (videoRef.current && streams[0]) {
        videoRef.current.srcObject = streams[0];
      }
    };

    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });

    // Use nginx proxy path (/go2rtc/) to avoid mixed-content blocking on HTTPS pages
    const go2rtcUrl = `/go2rtc/api/webrtc?src=${src}`;

    pc.createOffer()
      .then((offer) => pc.setLocalDescription(offer))
      .then(() =>
        fetch(go2rtcUrl, {
          method: "POST",
          headers: { "Content-Type": "application/sdp" },
          body: pc.localDescription!.sdp,
        }),
      )
      .then((res) => {
        if (!res.ok) throw new Error(`go2rtc: ${res.status}`);
        return res.text();
      })
      .then((sdp) => pc.setRemoteDescription({ type: "answer", sdp }))
      .catch((err) => {
        console.error("WebRTC error:", err);
        setError("Video unavailable");
      });

    return () => {
      pc.close();
    };
  }, [src]);

  if (error) {
    return (
      <div className="w-full aspect-video bg-gray-900 rounded-t-xl flex items-center justify-center">
        <p className="text-xs text-gray-500">{error}</p>
      </div>
    );
  }

  return (
    <video
      ref={videoRef}
      autoPlay
      playsInline
      muted
      className="w-full aspect-video rounded-t-xl bg-gray-900 object-cover"
    />
  );
}
