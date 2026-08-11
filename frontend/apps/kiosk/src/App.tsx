import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useScanLoop } from "./scan/useScanLoop";
import { apiBaseUrl } from "@attendance/api-client";
import type { FrameBurst, ServerMessage, Result, ErrorMessage, TokenRotation } from "@attendance/protocol";

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
  const [deviceTokenValue, setDeviceTokenValue] = useState<string>(() => {
    return localStorage.getItem("aegis_device_token") || SEED_DEVICE_TOKEN;
  });
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const [wsError, setWsError] = useState<string | null>(null);
  const [activeScan, setActiveScan] = useState(true);
  const [showEnroll, setShowEnroll] = useState(() => {
    try {
      return localStorage.getItem('aegis_show_enroll') === '1';
    } catch (e) {
      return false;
    }
  });

  // Persist showEnroll to localStorage so mode survives reloads
  useEffect(() => {
    try {
      localStorage.setItem('aegis_show_enroll', showEnroll ? '1' : '0');
    } catch (e) {
      // ignore
    }
  }, [showEnroll]);
  const [gatingStatus, setGatingStatus] = useState<string | null>("Initialize camera feed...");
  const [scanResult, setScanResult] = useState<Result | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [isMatching, setIsMatching] = useState(false);
  const [relaxedGating, setRelaxedGating] = useState(true);

  const [people, setPeople] = useState<{ id: string; display_name: string }[]>([]);

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

  // Fetch registered people
  const fetchPeople = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/people`, {
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setPeople(data);
      }
    } catch (err) {
      console.error("Failed to fetch registered people:", err);
    }
  }, []);

  // Delete specific registration
  const deletePerson = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete the registration for ${name}?`)) return;
    try {
      logMessage(`Deleting registration for ${name}...`, "info");
      const res = await fetch(`${apiBaseUrl}/api/people/${id}`, {
        method: "DELETE",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
        },
      });
      if (!res.ok) {
        throw new Error(`Delete failed: HTTP ${res.status}`);
      }
      logMessage(`Registration for ${name} successfully deleted.`, "info");
      fetchPeople();
    } catch (err: any) {
      logMessage(`Delete failed: ${err.message || err}`, "error");
    }
  };

  // Delete all registrations
  const deleteAllPeople = async () => {
    if (!confirm("Are you sure you want to delete ALL registrations? This will also clear all attendance records and logs.")) return;
    try {
      logMessage("Deleting all registrations...", "info");
      const res = await fetch(`${apiBaseUrl}/api/people`, {
        method: "DELETE",
        headers: {
          "x-admin-id": SEED_ADMIN_ID,
        },
      });
      if (!res.ok) {
        throw new Error(`Delete all failed: HTTP ${res.status}`);
      }
      logMessage("All registrations and attendance events deleted successfully.", "info");
      fetchPeople();
    } catch (err: any) {
      logMessage(`Delete all failed: ${err.message || err}`, "error");
    }
  };

  // Fetch device JWT token
  const fetchToken = async () => {
    try {
      const currentToken = localStorage.getItem("aegis_device_token") || SEED_DEVICE_TOKEN;
      logMessage(`Exchanging device credentials (prefix: ${currentToken.slice(0, 6)}...) for JWT scan token...`, "info");
      setWsStatus("connecting");
      setWsError(null);
      const res = await fetch(`${apiBaseUrl}/api/kiosk/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: SEED_DEVICE_ID,
          device_token: currentToken,
        }),
      });
      if (!res.ok) {
        if (res.status === 401) {
          logMessage("Device token invalid (401). Resetting cache to seed token.", "error");
          localStorage.removeItem("aegis_device_token");
          setDeviceTokenValue(SEED_DEVICE_TOKEN);
        }
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
          setIsMatching(false);
        } else if (msg.type === "checking") {
          setGatingStatus("Matching embedding...");
          setIsMatching(true);
        } else if (msg.type === "result") {
          setIsMatching(false);
          const result = msg as Result;
          if (result.status === "match" && result.person) {
            logMessage(`Match result: face matched successfully (UUID: ${result.person.id})`, "info");
            playBeep(880, "sine", 0.12);
            setTimeout(() => playBeep(1100, "sine", 0.15), 80);
            setScanResult(result);
            setScanError(null);
            // Dismiss success card after 3s
            setTimeout(() => setScanResult(null), 3000);
          } else {
            logMessage("Match result: unknown face (no match)", "error");
            playBeep(220, "triangle", 0.35);
            setScanError("Face not recognized. Please enroll first.");
            setTimeout(() => setScanError(null), 3000);
          }
        } else if (msg.type === "token_rotation") {
          const rotation = msg as TokenRotation;
          logMessage(`Device token rotated by server. Updating cached credentials.`, "info");
          localStorage.setItem("aegis_device_token", rotation.device_token);
          setDeviceTokenValue(rotation.device_token);
        } else if (msg.type === "error") {
          setIsMatching(false);
          const err = msg as ErrorMessage;
          logMessage(`Scan error event received: ${err.error.message} (code: ${err.error.code})`, "error");
          if (err.error.details) {
            logMessage(`Error Details: ${JSON.stringify(err.error.details)}`, "error");
          }
          playBeep(220, "triangle", 0.35);
          setScanError(getFriendlyErrorMessage(err.error.code, err.error.message));
          setTimeout(() => setScanError(null), 3000);
        }
      } catch (err) {
        logMessage(`Failed to parse server message: ${err}`, "error");
      }
    };

    ws.onclose = (event) => {
      logMessage(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason || "None"}`, "error");
      setWsStatus("disconnected");
      setIsMatching(false);
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
    };

    ws.onerror = (err) => {
      logMessage("WebSocket interface error encountered", "error");
      setWsStatus("disconnected");
      setIsMatching(false);
    };

    return () => {
      logMessage("Cleaning up WebSocket connection...", "info");
      ws.close();
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
    };
  }, [deviceToken, logMessage]);

  // Load registered people on mount and connection status change
  useEffect(() => {
    fetchPeople();
  }, [fetchPeople, wsStatus]);

  // Frame gating callbacks
  const handleBurstCaptured = useCallback((burst: FrameBurst) => {
    logMessage(`Gating rules passed. Submitting burst: ${burst.idempotency_key} (${burst.frames.length} frames)`, "info");
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      setIsMatching(true);
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

  // Memoize relaxed gating settings for webcam-friendly dev testing
  const scanSettings = useMemo(() => {
    if (relaxedGating) {
      return {
        min_bbox_area_pct: 3.5,
        min_interocular_px: 45,
        min_sharpness: 10.0,
        stability_iou: 0.75,
        luma_min: 15,
        luma_max: 245,
      };
    }
    return {};
  }, [relaxedGating]);

  // Initialize scan loop hook
  const { isLoadingModel, isScanRunning, resetLockout, detectedBbox, reason, metrics } = useScanLoop({
    videoRef,
    isScanActive: activeScan && wsStatus === "connected" && !scanResult && !showEnroll,
    facingMode: "user",
    scanMode: "continuous",
    settings: scanSettings,
    onBurstCaptured: handleBurstCaptured,
    onGatingFailed: handleGatingFailed,
    onGatingPassed: () => setGatingStatus("Perfect! Checking face..."),
    onDetected: () => playBeep(520, "sine", 0.05),
  });

  // Local Dev Enrollment Functionality
  const enrollFace = async () => {
    if (!enrollName.trim() || !videoRef.current) return;

    const normalizedName = enrollName.trim().toLowerCase();
    if (people.some((p) => p.display_name.trim().toLowerCase() === normalizedName)) {
      setEnrollError(`A profile with the name "${enrollName.trim()}" already exists. Please delete the existing profile or use a different name.`);
      return;
    }

    setIsEnrolling(true);
    setEnrollSuccess(null);
    setEnrollError(null);
    logMessage("Starting face enrollment", "info");

    let createdPersonId: string | null = null;

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
      createdPersonId = person.id;
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
      const data = await uploadRes.json();
      if (data.accepted_count === 0) {
        const firstRejection = data.results?.find((r: any) => r.status === "rejected");
        const errMsg = firstRejection?.rejection_message || "Face image was rejected by quality gates.";
        throw new Error(errMsg);
      }
      logMessage(`Face asset uploaded and committed successfully for UUID ${person.id}!`, "info");

      playBeep(880, "sine", 0.12);
      setTimeout(() => playBeep(1320, "sine", 0.15), 80);
      setEnrollSuccess(`Face registered successfully for ${person.display_name}!`);
      setEnrollName("");
      fetchPeople();

      // Auto-close enrollment panel after 3 seconds and guide user to scan mode
      setTimeout(() => {
        setShowEnroll(false);
        setEnrollSuccess(null);
        logMessage("Ready for attendance checks. Stand in front of the camera.", "info");
      }, 3000);
    } catch (err: any) {
      logMessage(`Enrollment failed: ${err.message || err}`, "error");

      // Cleanup orphaned/incomplete person profile
      if (createdPersonId) {
        logMessage(`Cleaning up incomplete/orphaned person record: ${createdPersonId}...`, "info");
        try {
          await fetch(`${apiBaseUrl}/api/people/${createdPersonId}`, {
            method: "DELETE",
            headers: {
              "x-admin-id": SEED_ADMIN_ID,
            },
          });
          logMessage("Incomplete person record successfully cleaned up.", "info");
          fetchPeople();
        } catch (cleanupErr) {
          console.error("Failed to clean up incomplete person record:", cleanupErr);
        }
      }

      playBeep(220, "triangle", 0.35);
      setEnrollError(err.message || "Failed to complete face enrollment");
    } finally {
      setIsEnrolling(false);
    }
  };

  const getGatingInstruction = (): string => {
    if (!reason) return "";
    if (reason.includes("bbox_area_too_small") || reason.includes("interocular_too_small")) {
      return "Too Far - Move Closer";
    }
    if (reason.includes("not_centered")) {
      return "Center Your Face";
    }
    if (reason.includes("blurry")) {
      return "Hold Still - Focusing";
    }
    if (reason.includes("invalid_luma") && metrics) {
      const minLuma = relaxedGating ? 15 : 40;
      const maxLuma = relaxedGating ? 245 : 220;
      if (metrics.luma < minLuma) {
        return "Too Dark - Need Light";
      }
      if (metrics.luma > maxLuma) {
        return "Too Bright / Glare";
      }
      return "Check Lighting";
    }
    if (reason.includes("multiple_faces")) {
      return "Ensure One Face Only";
    }
    return "Aligning Face...";
  };

  const getFriendlyErrorMessage = (code: string, rawMessage: string): string => {
    switch (code) {
      case "NO_FACE":
        return "No face detected. Please step in front of the camera.";
      case "MULTIPLE_FACES":
        return "Multiple faces detected. Please make sure only one person is in the frame.";
      case "FACE_TOO_SMALL":
        return "Please move closer to the camera.";
      case "LOW_QUALITY":
        return "Image is blurry or too dark. Please hold still and check lighting.";
      case "LIVENESS_FAILED":
        return "Verification failed. Please look directly at the camera.";
      case "AMBIGUOUS":
      case "LOW_CONFIDENCE":
        return "Scan was not clear enough. Please try again.";
      case "UNKNOWN_FACE":
        return "Face not recognized. Please register first.";
      case "COOLDOWN_ACTIVE":
        return "Already scanned recently. Please wait a moment.";
      case "RATE_LIMITED":
        return "Too many scan attempts. Please wait a few seconds.";
      case "LOCATION_CONFLICT":
        return "Location conflict. Please scan at your designated kiosk.";
      case "DEVICE_REVOKED":
        return "Kiosk authorization revoked. Please contact administrator.";
      case "SCAN_BACKEND_UNAVAILABLE":
        if (rawMessage.includes("implicit open scan session")) {
          return "Session initialized. Please try scanning now.";
        }
        return "System temporarily unavailable. Please try again.";
      default:
        return "Face scan failed. Please try again.";
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

          {/* Mode Badge + Toggle - always visible so users know current mode */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                const enteringEnroll = !showEnroll;
                setShowEnroll(enteringEnroll);
                setEnrollSuccess(null);
                setEnrollError(null);
                // When entering enrollment mode, pause scanning; when leaving, resume scanning
                setActiveScan(!enteringEnroll);
              }}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors border ${showEnroll ? "bg-amber-500 text-zinc-950 border-amber-600" : "bg-emerald-500 text-zinc-950 border-emerald-600"}`}
              title={showEnroll ? "Click to switch to Scan Mode" : "Click to switch to Registration Mode"}
            >
              {showEnroll ? "Registration Mode" : "Scan Mode"}
            </button>
          </div>

          {wsStatus === "disconnected" && (
            <button
              onClick={fetchToken}
              className="rounded-full bg-cyan-500 px-4 py-1 text-xs font-semibold text-zinc-950 hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20"
            >
              Connect Kiosk
            </button>
          )}

          {/* Explicit Start/Stop Scan control visible when connected */}
          {wsStatus === 'connected' && (
            <button
              onClick={() => {
                if (activeScan) {
                  setActiveScan(false);
                } else {
                  setActiveScan(true);
                  // ensure not in enroll mode
                  setShowEnroll(false);
                }
              }}
              className={`ml-2 rounded-full px-3 py-1 text-xs font-semibold transition-colors border ${activeScan ? 'bg-red-500 text-white border-red-600' : 'bg-emerald-500 text-zinc-950 border-emerald-600'}`}
            >
              {activeScan ? 'Stop Scanning' : 'Start Scanning'}
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

            {/* Enrollment Guide Overlay */}
            {isScanRunning && showEnroll && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none bg-black/10">
                {/* Face Silhouette Guide */}
                <div className="h-64 w-48 rounded-[120px] border-2 border-dashed border-cyan-400 shadow-[0_0_15px_#22d3ee] flex items-center justify-center animate-[pulse_2s_infinite]">
                  <div className="h-56 w-40 rounded-[100px] border border-cyan-400/30" />
                </div>
                {/* Text guide */}
                <div className="absolute bottom-6 bg-cyan-950/95 border border-cyan-500/30 rounded-full px-4 py-1.5 text-xs text-cyan-200 font-semibold tracking-wide shadow-lg backdrop-blur-sm">
                  Position your face in the silhouette and click "Capture & Register"
                </div>
              </div>
            )}

            {/* Disconnected Overlay */}
            {wsStatus !== "connected" && !isLoadingModel && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/80 backdrop-blur-sm z-10">
                <svg className="h-12 w-12 text-zinc-500 mb-3 animate-[pulse_2s_infinite]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-3.536 4.978 4.978 0 011.414-3.536m0 0L8.464 8.464M5.636 5.636a9 9 0 000 12.728m0 0L3 21" />
                </svg>
                <p className="text-zinc-300 text-sm font-semibold tracking-wide mb-1">Kiosk Offline</p>
                <p className="text-zinc-500 text-xs">Click "Connect Kiosk" in the header to start scanning</p>
              </div>
            )}

            {/* Scan Mode Active Indicator */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute top-4 left-4 bg-zinc-950/85 border border-cyan-500/30 rounded-full px-3 py-1 text-[10px] text-cyan-400 font-semibold tracking-wider uppercase backdrop-blur-sm z-10 flex items-center gap-1.5 shadow-lg shadow-cyan-500/10">
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                <span>Kiosk Scan Mode Active</span>
              </div>
            )}

            {/* Real-time Bounding Box Overlay */}
            {isScanRunning && wsStatus === "connected" && !scanResult && detectedBbox && (
              <div
                style={{
                  left: `${100 - detectedBbox.x - detectedBbox.w}%`,
                  top: `${detectedBbox.y}%`,
                  width: `${detectedBbox.w}%`,
                  height: `${detectedBbox.h}%`,
                }}
                className={`absolute border-2 rounded-2xl transition-all duration-75 pointer-events-none ${
                  showEnroll 
                    ? "border-cyan-400 shadow-[0_0_8px_#22d3ee]" 
                    : reason 
                    ? "border-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.5)]" 
                    : "border-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]"
                }`}
              >
                <div className={`absolute -top-7 left-0 px-2 py-0.5 rounded text-[10px] font-semibold text-zinc-950 uppercase tracking-wider backdrop-blur-sm whitespace-nowrap ${
                  showEnroll 
                    ? "bg-cyan-400" 
                    : reason 
                    ? "bg-amber-400" 
                    : "bg-emerald-400"
                }`}>
                  {showEnroll 
                    ? "Enrolling..." 
                    : reason 
                    ? getGatingInstruction() 
                    : "Stable - Scanning..."}
                </div>
              </div>
            )}

            {/* Analyzing Overlay */}
            {isMatching && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/60 backdrop-blur-[2px] z-10 animate-fade-in">
                <div className="relative h-28 w-28 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border-4 border-cyan-500/20 border-t-cyan-400 animate-spin" />
                  <svg className="h-10 w-10 text-cyan-400 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <p className="text-cyan-300 text-sm font-semibold tracking-wider uppercase mt-4 animate-pulse">
                  Analyzing Biometrics
                </p>
                <p className="text-zinc-400 text-xs mt-1">
                  Matching face against gallery...
                </p>
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

              {/* Relax scan criteria toggle */}
              <div className="flex items-center justify-between bg-zinc-900/40 border border-white/5 rounded-2xl px-4 py-3 mb-4 select-none">
                <div className="flex flex-col gap-0.5 pr-2">
                  <span className="text-xs font-semibold text-zinc-300">Relax Scan Criteria</span>
                  <span className="text-[10px] text-zinc-500 leading-tight">Bypasses strict distance/lighting gates for easy local webcam testing</span>
                </div>
                <button
                  onClick={() => setRelaxedGating(!relaxedGating)}
                  className={`relative inline-flex h-5.5 w-10 shrink-0 items-center rounded-full transition-colors duration-200 ${
                    relaxedGating ? "bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.3)]" : "bg-zinc-800"
                  }`}
                >
                  <span
                    className={`inline-block h-4.5 w-4.5 transform rounded-full bg-zinc-950 transition-transform duration-200 ${
                      relaxedGating ? "translate-x-5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>

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

              {/* List of current registrations */}
              <div className="mt-4 pt-4 border-t border-white/5 space-y-3">
                <div className="flex justify-between items-center">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase">
                    Registered Profiles ({people.length})
                  </h3>
                  {people.length > 0 && (
                    <button
                      onClick={deleteAllPeople}
                      className="text-[10px] text-red-400 hover:text-red-300 font-semibold transition-colors bg-red-500/10 hover:bg-red-500/20 px-2 py-0.5 rounded"
                    >
                      Delete All
                    </button>
                  )}
                </div>

                {people.length === 0 ? (
                  <p className="text-[11px] text-zinc-500 italic">No face profiles registered yet.</p>
                ) : (
                  <div className="max-h-36 overflow-y-auto space-y-1.5 scrollbar-thin pr-1">
                    {people.map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center justify-between bg-zinc-900/50 border border-white/5 rounded-xl px-3 py-2 text-xs hover:border-white/10 transition-colors"
                      >
                        <span className="font-medium truncate text-zinc-300">{p.display_name}</span>
                        <button
                          onClick={() => deletePerson(p.id, p.display_name)}
                          className="text-red-400 hover:text-red-300 transition-all p-1 hover:bg-red-500/10 rounded"
                          title="Delete profile"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
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
                <li>Click <span className="text-cyan-300">Enroll Face Profile</span>, enter your name, and click <span className="text-cyan-300">Capture & Register</span>.</li>
                <li>Wait for the green success confirmation card (it will auto-close in 3s).</li>
                <li>In <strong>Scan Mode</strong> (when enrollment is closed), look directly at the webcam inside the scanning circle.</li>
                <li>The app will automatically match your face and display a green <strong>"Punch Success"</strong> card!</li>
              </ol>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
