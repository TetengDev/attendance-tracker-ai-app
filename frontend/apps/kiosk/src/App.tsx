import { useCallback, useEffect, useRef, useState } from "react";
import { useScanLoop } from "./scan/useScanLoop";
import { apiBaseUrl } from "@attendance/api-client";
import type { FrameBurst, ServerMessage, Result, ErrorMessage } from "@attendance/protocol";

// Configuration for local dev seed device
const SEED_DEVICE_ID = "ee2872c4-f685-4843-b64d-8b29edfd086a";
const SEED_DEVICE_TOKEN = "seed-device-token";
const SEED_ADMIN_ID = "3db96e05-898f-4555-b869-3a85cece722e";

// Browser Web Audio synthesizer helper for alerts
const playBeep = (freq = 880, type: OscillatorType = "sine", duration = 0.15) => {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (e) {
    console.error("Audio beep failed:", e);
  }
};

export function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  
  // App state
  const [deviceToken, setDeviceToken] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const [wsError, setWsError] = useState<string | null>(null);
  const [activeScan, setActiveScan] = useState(true);
  const [showEnroll, setShowEnroll] = useState(false);
  const [gatingStatus, setGatingStatus] = useState<string | null>("Initialize camera feed...");
  const [scanResult, setScanResult] = useState<Result | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  // Enrollment state
  const [enrollName, setEnrollName] = useState("");
  const [isEnrolling, setIsEnrolling] = useState(false);
  const [enrollSuccess, setEnrollSuccess] = useState<string | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);

  // WebSocket reference
  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatIntervalRef = useRef<number | null>(null);

  // Live console logs state
  const [logs, setLogs] = useState<string[]>([]);

  // Logger helper that logs locally to state and uploads to the server log file
  const logMessage = useCallback((msg: string, level: "info" | "error" = "info") => {
    const time = new Date().toLocaleTimeString();
    const formatted = `[${time}] ${msg}`;
    setLogs((prev) => [formatted, ...prev].slice(0, 100));
    
    fetch(`${apiBaseUrl}/api/kiosk/logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: `${level.toUpperCase()}: ${msg}` }),
    }).catch((err) => console.error("Client log upload failed:", err));
  }, []);

  // Fetch device JWT token
  const fetchToken = async () => {
    try {
      logMessage("Exchanging seed device credentials for JWT scan token...", "info");
      setWsStatus("connecting");
      setWsError(null);
      const res = await fetch(`${apiBaseUrl}/api/kiosk/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: SEED_DEVICE_ID,
          device_token: SEED_DEVICE_TOKEN,
        }),
      });
      if (!res.ok) {
        throw new Error(`Token exchange failed: HTTP ${res.status}`);
      }
      const data = await res.json();
      logMessage("JWT token successfully exchanged.", "info");
      setDeviceToken(data.device_token_jwt);
    } catch (err: any) {
      logMessage(`Token exchange failed: ${err.message || err}`, "error");
      setWsStatus("disconnected");
      setWsError(err.message || "Failed to exchange device token");
    }
  };

  // Connect to WebSocket using token
  useEffect(() => {
    if (!deviceToken) return;

    const wsUrl = apiBaseUrl.replace(/^http/, "ws") + "/api/kiosk/ws";
    logMessage(`Connecting to WebSocket interface: ${wsUrl}`, "info");
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      logMessage("WebSocket connection opened. Sending hello handshake...", "info");
      setWsStatus("connected");
      // Send Hello Handshake
      ws.send(
        JSON.stringify({
          type: "hello",
          device_token_jwt: deviceToken,
          app_version: "1.0.0",
          camera_label: "Dev Webcam",
        })
      );

      // Start Heartbeat interval every 5s
      heartbeatIntervalRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "heartbeat",
              fps: 15,
              queue_depth: 0,
              error_count: 0,
              clock_skew_ms: 0,
            })
          );
        }
      }, 5000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        logMessage(`Received WebSocket event: ${msg.type}`, "info");
        if (msg.type === "ready") {
          logMessage("WebSocket handshake success: ready for scans.", "info");
          setGatingStatus("Ready for face scan");
        } else if (msg.type === "checking") {
          setGatingStatus("Matching embedding...");
        } else if (msg.type === "result") {
          const result = msg as Result;
          if (result.status === "match" && result.person) {
            logMessage(`Match result: ${result.person.display_name}`, "info");
            playBeep(880, "sine", 0.12);
            setTimeout(() => playBeep(1100, "sine", 0.15), 80);
            setScanResult(result);
            setScanError(null);
            // Dismiss success card after 3s
            setTimeout(() => setScanResult(null), 3000);
          } else {
            logMessage("Match result: unknown face (no match)", "error");
            playBeep(220, "triangle", 0.35);
            setScanError("Face not recognized");
            setTimeout(() => setScanError(null), 3000);
          }
        } else if (msg.type === "error") {
          const err = msg as ErrorMessage;
          logMessage(`Scan error event received: ${err.error.message}`, "error");
          playBeep(220, "triangle", 0.35);
          setScanError(err.error.message);
          setTimeout(() => setScanError(null), 3000);
        }
      } catch (err) {
        logMessage(`Failed to parse server message: ${err}`, "error");
      }
    };

    ws.onclose = (event) => {
      logMessage(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason || "None"}`, "error");
      setWsStatus("disconnected");
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
    };

    ws.onerror = (err) => {
      logMessage("WebSocket interface error encountered", "error");
      setWsStatus("disconnected");
    };

    return () => {
      logMessage("Cleaning up WebSocket connection...", "info");
      ws.close();
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
    };
  }, [deviceToken, logMessage]);

  // Frame gating callbacks
  const handleBurstCaptured = useCallback((burst: FrameBurst) => {
    logMessage(`Gating rules passed. Submitting burst: ${burst.idempotency_key} (${burst.frames.length} frames)`, "info");
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(burst));
    } else {
      logMessage("WebSocket not open. Dropped burst submission.", "error");
    }
  }, [logMessage]);

  const handleGatingFailed = useCallback((reason: string) => {
    // Translate gate warnings to human-friendly feedback
    if (reason.includes("min_bbox_area_pct")) {
      setGatingStatus("Please move closer");
    } else if (reason.includes("min_interocular_px")) {
      setGatingStatus("Face too far");
    } else if (reason.includes("max_center_offset_pct")) {
      setGatingStatus("Please center your face");
    } else if (reason.includes("min_sharpness")) {
      setGatingStatus("Hold still, focusing...");
    } else if (reason.includes("luma")) {
      setGatingStatus("Check lighting conditions");
    } else {
      setGatingStatus(reason);
    }
  }, []);

  // Initialize scan loop hook
  const { isLoadingModel, isScanRunning, resetLockout } = useScanLoop({
    videoRef,
    isScanActive: activeScan && wsStatus === "connected" && !scanResult && !showEnroll,
    facingMode: "user",
    scanMode: "continuous",
    onBurstCaptured: handleBurstCaptured,
    onGatingFailed: handleGatingFailed,
    onGatingPassed: () => setGatingStatus("Perfect! Checking face..."),
    onDetected: () => playBeep(520, "sine", 0.05),
  });

  // Local Dev Enrollment Functionality
  const enrollFace = async () => {
    if (!enrollName.trim() || !videoRef.current) return;
    setIsEnrolling(true);
    setEnrollSuccess(null);
    setEnrollError(null);
    logMessage(`Starting face enrollment for: "${enrollName.trim()}"`, "info");

    try {
      // 1. Create a person record
      logMessage("API Call: Creating person record...", "info");
      const personRes = await fetch(`${apiBaseUrl}/api/people`, {
        method: "POST",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          display_name: enrollName.trim(),
          kind: "staff",
        }),
      });
      if (!personRes.ok) {
        throw new Error(`Failed to create person: HTTP ${personRes.status}`);
      }
      const person = await personRes.json();
      logMessage(`Person record created: UUID ${person.id}`, "info");

      // 2. Submit consent
      logMessage("API Call: Submitting biometric consent...", "info");
      const consentRes = await fetch(`${apiBaseUrl}/api/consents/biometric-enrollment`, {
        method: "POST",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          person_id: person.id,
          grantor: "self",
          method: "admin_attestation",
          policy_version: "1.0",
        }),
      });
      if (!consentRes.ok) {
        throw new Error(`Failed to create consent: HTTP ${consentRes.status}`);
      }
      logMessage("Biometric consent submitted successfully.", "info");

      // 3. Authorize consent
      logMessage("API Call: Authorizing biometric consent...", "info");
      const authRes = await fetch(`${apiBaseUrl}/api/consents/biometric-enrollment/authorize`, {
        method: "POST",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          person_id: person.id,
          policy_version: "1.0",
        }),
      });
      if (!authRes.ok) {
        throw new Error(`Failed to authorize consent: HTTP ${authRes.status}`);
      }
      logMessage("Biometric consent authorized successfully.", "info");

      // 4. Capture a canvas frame from the video
      logMessage("Capturing current camera frame to canvas...", "info");
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Could not construct 2D canvas context");
      ctx.drawImage(videoRef.current, 0, 0, 640, 480);

      // Convert to blob
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), "image/jpeg", 0.95)
      );
      if (!blob) throw new Error("Could not compress frame to JPEG");

      // 5. Upload enrollment face asset
      logMessage("API Call: Uploading and committing face asset...", "info");
      const formData = new FormData();
      formData.append("files", blob, "enrollment.jpg");
      formData.append("policy_version", "1.0");

      const uploadRes = await fetch(`${apiBaseUrl}/api/enrollment/${person.id}/upload`, {
        method: "POST",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
        },
        body: formData,
      });

      if (!uploadRes.ok) {
        const errData = await uploadRes.json().catch(() => ({}));
        throw new Error(errData.error?.message || `Upload failed: HTTP ${uploadRes.status}`);
      }
      logMessage(`Face asset uploaded and committed successfully for ${person.display_name}!`, "info");

      playBeep(880, "sine", 0.12);
      setTimeout(() => playBeep(1320, "sine", 0.15), 80);
      setEnrollSuccess(`Face registered successfully for ${person.display_name}!`);
      setEnrollName("");
    } catch (err: any) {
      logMessage(`Enrollment failed: ${err.message || err}`, "error");
      playBeep(220, "triangle", 0.35);
      setEnrollError(err.message || "Failed to complete face enrollment");
    } finally {
      setIsEnrolling(false);
    }
  };

  return (
    <main className="relative min-h-screen bg-zinc-950 font-sans text-zinc-100 antialiased overflow-hidden">
      {/* Decorative neon gradient overlays */}
      <div className="absolute -left-48 -top-48 h-96 w-96 rounded-full bg-cyan-500/10 blur-[100px]" />
      <div className="absolute -bottom-48 -right-48 h-96 w-96 rounded-full bg-indigo-500/10 blur-[100px]" />

      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6 border-b border-white/5">
        <div className="flex items-center gap-3">
          <span className="h-2.5 w-2.5 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.7)]" />
          <span className="font-semibold tracking-tight text-lg">Aegis Biometrics</span>
        </div>
        <div className="flex items-center gap-4">
          {/* WS Status Indicator */}
          <div className="flex items-center gap-2 rounded-full bg-white/5 px-3.5 py-1 text-xs border border-white/10">
            {wsStatus === "connected" ? (
              <>
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                <span className="text-zinc-300">Connected</span>
              </>
            ) : wsStatus === "connecting" ? (
              <>
                <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-zinc-300">Connecting</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-red-500" />
                <span className="text-zinc-300">Disconnected</span>
              </>
            )}
          </div>
          {wsStatus === "disconnected" && (
            <button
              onClick={fetchToken}
              className="rounded-full bg-cyan-500 px-4 py-1 text-xs font-semibold text-zinc-950 hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20"
            >
              Connect Kiosk
            </button>
          )}
        </div>
      </header>

      <section className={`mx-auto grid max-w-5xl gap-8 px-6 py-12 ${import.meta.env.DEV ? "md:grid-cols-3" : "md:grid-cols-1 justify-center max-w-2xl"}`}>
        {/* Left Side: Scan Feed and Centering Overlays */}
        <div className={import.meta.env.DEV ? "md:col-span-2 flex flex-col gap-4" : "flex flex-col gap-4"}>
          <div className="relative aspect-[4/3] rounded-3xl overflow-hidden border border-white/10 bg-black shadow-2xl">
            {/* Live Camera Feed */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="h-full w-full object-cover transform scale-x-[-1]"
            />

            {/* Glowing Laser Scan Bar */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-85 shadow-[0_0_12px_#22d3ee] animate-scan-line pointer-events-none" />
            )}

            {/* Face centering guide target */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="h-56 w-56 rounded-full border-2 border-dashed border-cyan-400/30 flex items-center justify-center animate-[spin_40s_linear_infinite]">
                  <div className="h-48 w-48 rounded-full border border-cyan-400/20" />
                </div>
              </div>
            )}

            {/* Loading / Startup Overlay */}
            {isLoadingModel && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/90 backdrop-blur-sm z-10">
                <div className="h-10 w-10 border-4 border-cyan-500/30 border-t-cyan-400 rounded-full animate-spin mb-4" />
                <p className="text-zinc-400 text-sm tracking-wide">Loading Face Engine WASM Models...</p>
              </div>
            )}

            {/* Attendance Punch Result Notification Modal */}
            {scanResult && scanResult.person && (
              <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/85 backdrop-blur-md z-20 animate-fade-in">
                <div className="flex flex-col items-center text-center p-6 max-w-sm rounded-3xl bg-zinc-900 border border-white/10 shadow-2xl animate-scale-up">
                  <div className="h-20 w-20 rounded-full bg-emerald-500/10 border-2 border-emerald-500/30 flex items-center justify-center mb-5 animate-pulse">
                    <svg className="h-10 w-10 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <h3 className="text-2xl font-bold tracking-tight text-white mb-2">Punch Success</h3>
                  <p className="text-zinc-300 text-lg mb-1">{scanResult.person.display_name}</p>
                  <p className="text-zinc-500 text-xs uppercase tracking-widest mb-4">
                    {scanResult.direction === "in" ? "CHECK-IN" : "CHECK-OUT"} • {new Date(scanResult.occurred_at).toLocaleTimeString()}
                  </p>
                  <span className="text-xs text-zinc-400 bg-white/5 border border-white/10 rounded-full px-3 py-1">
                    Attendance Logged Durably
                  </span>
                </div>
              </div>
            )}

            {/* Gating Error Notification */}
            {scanError && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-red-950/90 border border-red-500/30 backdrop-blur-md rounded-2xl px-5 py-3.5 shadow-2xl z-20 animate-scale-up">
                <span className="h-2 w-2 rounded-full bg-red-400 animate-pulse" />
                <span className="text-red-200 text-sm font-medium">{scanError}</span>
              </div>
            )}
          </div>

          {/* Real-time scanning ticker / Gating feedback */}
          <div className="flex items-center gap-3.5 rounded-2xl border border-white/5 bg-white/5 px-5 py-3 text-sm text-zinc-400 font-medium">
            <span className={`h-2.5 w-2.5 rounded-full ${wsStatus === "connected" && isScanRunning ? "bg-cyan-400 animate-pulse" : "bg-zinc-600"}`} />
            <span>{gatingStatus}</span>
            {isScanRunning && wsStatus === "connected" && (
              <button
                onClick={resetLockout}
                className="ml-auto text-xs text-cyan-400 hover:text-cyan-300 transition-colors bg-cyan-400/10 px-2.5 py-1 rounded-lg"
              >
                Reset Lockout
              </button>
            )}
          </div>
        </div>

        {/* Right Side: Setup instructions and Dev Tools */}
        {import.meta.env.DEV && (
          <div className="flex flex-col gap-6">
            {/* Local Dev Controls */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-md shadow-lg">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-cyan-300">Local Dev Tools</h2>
                <span className="text-[10px] bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 px-2 py-0.5 rounded-full uppercase font-mono">Ready</span>
              </div>
              
              <p className="text-xs text-zinc-400 mb-6">
                Use this shortcut to easily seed new profiles directly via your webcam, enabling local matching scans.
              </p>

              <button
                onClick={() => {
                  setShowEnroll(!showEnroll);
                  setEnrollSuccess(null);
                  setEnrollError(null);
                }}
                className="w-full rounded-2xl border border-white/10 hover:border-white/20 bg-white/5 hover:bg-white/10 py-3 text-sm font-medium transition-all flex items-center justify-center gap-2 mb-4"
              >
                {showEnroll ? "Close Enrollment" : "Enroll Face Profile"}
              </button>

              {showEnroll && (
                <div className="space-y-4 pt-4 border-t border-white/5 animate-fade-in">
                  <div>
                    <label htmlFor="enroll-name" className="block text-xs font-semibold text-zinc-400 uppercase mb-2">
                      Person Name
                    </label>
                    <input
                      id="enroll-name"
                      type="text"
                      placeholder="e.g. Alice Cooper"
                      value={enrollName}
                      onChange={(e) => setEnrollName(e.target.value)}
                      disabled={isEnrolling}
                      className="w-full rounded-xl bg-zinc-900 border border-white/10 px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500 transition-colors"
                    />
                  </div>

                  <button
                    onClick={enrollFace}
                    disabled={isEnrolling || !enrollName.trim()}
                    className="w-full rounded-xl bg-cyan-500 disabled:bg-zinc-800 disabled:text-zinc-500 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-cyan-400 transition-all shadow-lg shadow-cyan-500/10 flex items-center justify-center gap-2"
                  >
                    {isEnrolling ? (
                      <>
                        <div className="h-4 w-4 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin" />
                        Registering Biometrics...
                      </>
                    ) : (
                      "Capture & Register"
                    )}
                  </button>

                  {enrollSuccess && (
                    <div className="rounded-xl bg-emerald-950/50 border border-emerald-500/20 p-3 text-xs text-emerald-300">
                      {enrollSuccess}
                    </div>
                  )}

                  {enrollError && (
                    <div className="rounded-xl bg-red-950/50 border border-red-500/20 p-3 text-xs text-red-300">
                      {enrollError}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Real-time Logs Console */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-md shadow-lg flex flex-col h-80">
              <div className="flex justify-between items-center mb-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-cyan-300">Live Connection Logs</h2>
                <button
                  onClick={() => setLogs([])}
                  className="text-[10px] text-zinc-400 hover:text-cyan-300 bg-white/5 px-2.5 py-1 rounded-md border border-white/5 transition-all"
                >
                  Clear Logs
                </button>
              </div>
              <div className="flex-1 overflow-y-auto font-mono text-[10px] text-zinc-300 space-y-1.5 p-3 rounded-xl bg-zinc-950/70 border border-white/5 select-text scrollbar-thin">
                {logs.length === 0 ? (
                  <p className="text-zinc-500 italic">No logs recorded yet.</p>
                ) : (
                  logs.map((log, idx) => (
                    <div
                      key={idx}
                      className={
                        log.includes("ERROR:") || log.includes("failed") || log.includes("closed")
                          ? "text-red-400"
                          : log.includes("success") || log.includes("Success") || log.includes("opened")
                          ? "text-emerald-400"
                          : "text-zinc-300"
                      }
                    >
                      {log}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Quickstart Reference Box */}
            <div className="rounded-3xl border border-white/5 bg-zinc-900/50 p-6 space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Step-by-step Test</h3>
              <ol className="list-decimal list-inside space-y-2.5 text-xs text-zinc-400">
                <li>Click <span className="text-cyan-300">Connect Kiosk</span> to connect the WebSocket to the local backend.</li>
                <li>Toggle <span className="text-cyan-300">Enroll Face Profile</span>.</li>
                <li>Input your name and click <span className="text-cyan-300">Capture & Register</span> to save your face.</li>
                <li>Wait for success confirmation.</li>
                <li>Look directly at the webcam within the guide lines to trigger the scan punch!</li>
              </ol>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
