import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useScanLoop } from "./scan/useScanLoop";
import { apiBaseUrl as defaultApiBaseUrl } from "@attendance/api-client";
import { enqueueOfflineScan, getOfflineScans, removeOfflineScan, getOfflineQueueDepth } from "./utils/offlineQueue";
import type { FrameBurst, ServerMessage, Result, ErrorMessage, TokenRotation, SettingsPush } from "@attendance/protocol";

// Configuration for local dev seed device
const SEED_DEVICE_ID = "ee2872c4-f685-4843-b64d-8b29edfd086a";
const SEED_DEVICE_TOKEN = "seed-device-token";
const SEED_ADMIN_ID = "14d75b41-d558-4a73-9369-93f32ef86a70";

// Browser Web Audio synthesizer helper for alerts
let sharedAudioCtx: AudioContext | null = null;
const getSharedAudioCtx = () => {
  if (!sharedAudioCtx) {
    sharedAudioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
  return sharedAudioCtx;
};

const unlockAudioContext = () => {
  try {
    const ctx = getSharedAudioCtx();
    if (ctx.state === "suspended") {
      ctx.resume().catch(e => console.warn("Failed to resume AudioContext:", e));
    }
  } catch (e) {
    console.error("Audio Context unlock failed:", e);
  }
};

const playBeep = (freq = 880, type: OscillatorType = "sine", duration = 0.15) => {
  try {
    const ctx = getSharedAudioCtx();
    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }
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

function ConnectionSettingsModal({ isOpen, onClose, currentUrl, onSave }: { isOpen: boolean; onClose: () => void; currentUrl: string; onSave: (url: string, pairingCode?: string) => void }) {
  const [url, setUrl] = useState(currentUrl);
  const [pairingCode, setPairingCode] = useState("");

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-surface-card rounded-2xl border border-hairline w-full max-w-md overflow-hidden animate-scale-up text-white shadow-2xl shadow-black/80">
        <div className="px-6 py-4 border-b border-hairline flex items-center justify-between">
          <h2 className="text-xs font-bold uppercase tracking-widest text-white">Server Connection Settings</h2>
          <button onClick={onClose} className="text-muted-color hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); onSave(url, pairingCode.trim() || undefined); setPairingCode(""); onClose(); }} className="p-6">
          <div className="space-y-4">
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-muted-color mb-1.5">Backend API Server URL</label>
              <input 
                required 
                type="text" 
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="w-full rounded-xl bg-surface-soft border border-hairline text-xs py-2.5 px-3.5 outline-none text-white focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all font-mono" 
                placeholder="e.g. http://192.168.1.100:8001" 
              />
              <p className="text-[9px] text-muted-color mt-2 uppercase tracking-wider leading-relaxed">
                Enter your computer's local LAN IP address and port (e.g. port 8001) to connect the physical mobile device or simulator to the backend.
              </p>
            </div>
            <div className="border-t border-hairline pt-4">
              <label className="block text-[10px] font-bold uppercase tracking-wider text-muted-color mb-1.5">Device Pairing Code (Optional)</label>
              <input 
                type="text" 
                value={pairingCode}
                onChange={(e) => setPairingCode(e.target.value.toUpperCase())}
                className="w-full rounded-xl bg-surface-soft border border-hairline text-xs py-2.5 px-3.5 outline-none text-white focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all font-mono" 
                placeholder="e.g. ABCDEFGH" 
                maxLength={8}
              />
              <p className="text-[9px] text-muted-color mt-2 uppercase tracking-wider leading-relaxed">
                If the seed token is invalid (401), generate a pairing code in the Admin Console (Devices tab), enter it here, and save to pair this client.
              </p>
            </div>
          </div>
          <div className="mt-8 flex justify-end gap-3 border-t border-hairline pt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 text-xs font-bold text-muted-color hover:text-white uppercase tracking-widest transition-all active:scale-[0.96]">Cancel</button>
            <button type="submit" className="bg-primary hover:bg-primary/90 text-white font-bold py-2.5 px-5 rounded-xl text-xs uppercase tracking-widest transition-all active:scale-[0.96] shadow-lg shadow-primary/20">
              Save & Reconnect
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  
  // Dynamic API configuration
  const [apiUrl, setApiUrl] = useState(() => {
    return localStorage.getItem("aegis_api_url") || defaultApiBaseUrl;
  });
  const [isConnModalOpen, setIsConnModalOpen] = useState(false);
  const apiBaseUrl = apiUrl;
  
  // App state
  const [deviceToken, setDeviceToken] = useState<string | null>(null);
  const [deviceTokenValue, setDeviceTokenValue] = useState<string>(() => {
    return localStorage.getItem("aegis_device_token") || SEED_DEVICE_TOKEN;
  });
  const [deviceId, setDeviceId] = useState<string>(() => {
    return localStorage.getItem("aegis_device_id") || SEED_DEVICE_ID;
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
  const [scanInfo, setScanInfo] = useState<string | null>(null);
  const [isMatching, setIsMatching] = useState(false);
  const [pinValue, setPinValue] = useState("");
  const [relaxedGating, setRelaxedGating] = useState(true);
  const [kioskSettings, setKioskSettings] = useState<Record<string, any>>({});
  const [people, setPeople] = useState<{ id: string; display_name: string; kind?: string }[]>([]);
  const [isAppBackgrounded, setIsAppBackgrounded] = useState(false);

  // iOS Safari specific visibility tracking to restart stalled camera feeds
  useEffect(() => {
    const handleVisibility = () => {
      const hidden = document.visibilityState === "hidden";
      setIsAppBackgrounded(hidden);
      if (!hidden && videoRef.current && videoRef.current.srcObject) {
        // iOS requires explicit play() call on user return to active tab
        videoRef.current.play().catch(e => console.warn("Video stream play failed on foreground return:", e));
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  // Web Audio context gesture unlocking listener for iOS alerts
  useEffect(() => {
    const unlock = () => {
      unlockAudioContext();
      window.removeEventListener("click", unlock);
      window.removeEventListener("touchstart", unlock);
      window.removeEventListener("keydown", unlock);
    };
    window.addEventListener("click", unlock);
    window.addEventListener("touchstart", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("click", unlock);
      window.removeEventListener("touchstart", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  // Dynamically apply branding colors from server settings to CSS variables
  useEffect(() => {
    const primaryColor = (kioskSettings["branding.primary_color"] as string | undefined) || "#22d3ee";
    const accentColor = (kioskSettings["branding.accent_color"] as string | undefined) || "#10b981";
    document.documentElement.style.setProperty("--primary-color", primaryColor);
    document.documentElement.style.setProperty("--accent-color", accentColor);
  }, [kioskSettings]);

  const [queueDepth, setQueueDepth] = useState(0);

  useEffect(() => {
    getOfflineQueueDepth().then(setQueueDepth).catch(console.error);
  }, []);

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (queueDepth > 0) {
        e.preventDefault();
        e.returnValue = "Warning: You have unsent offline scans. If you close this page, they might be lost.";
        return e.returnValue;
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [queueDepth]);

  // Enrollment state
  const [enrollName, setEnrollName] = useState("");
  const [isEnrolling, setIsEnrolling] = useState(false);
  const [enrollSuccess, setEnrollSuccess] = useState<string | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState<"user" | "environment">("user");

  useEffect(() => {
    if (kioskSettings["kiosk.camera_facing"]) {
      setFacingMode(kioskSettings["kiosk.camera_facing"] as "user" | "environment");
    }
  }, [kioskSettings]);

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
      const currentDeviceId = localStorage.getItem("aegis_device_id") || SEED_DEVICE_ID;
      logMessage(`Exchanging device credentials (prefix: ${currentToken.slice(0, 6)}...) for JWT scan token...`, "info");
      setWsStatus("connecting");
      setWsError(null);
      const res = await fetch(`${apiBaseUrl}/api/kiosk/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: currentDeviceId,
          device_token: currentToken,
        }),
      });
      if (!res.ok) {
        if (res.status === 401) {
          logMessage("Device token invalid (401). Resetting cache to seed token.", "error");
          localStorage.removeItem("aegis_device_token");
          localStorage.removeItem("aegis_device_id");
          setDeviceTokenValue(SEED_DEVICE_TOKEN);
          setDeviceId(SEED_DEVICE_ID);
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
          replayOfflineScans();
        } else if (msg.type === "checking") {
          setGatingStatus("Matching embedding...");
          setIsMatching(true);
        } else if (msg.type === "result") {
          setIsMatching(false);
          const result = msg as Result;
          if (result.status === "accepted" && result.person) {
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
        } else if (msg.type === "settings_push") {
          const push = msg as SettingsPush;
          logMessage(`Received settings push (version: ${push.settings_version})`, "info");
          setKioskSettings(push.payload);
        } else if (msg.type === "token_rotation") {
          const rotation = msg as TokenRotation;
          logMessage(`Device token rotated by server. Updating cached credentials.`, "info");
          localStorage.setItem("aegis_device_token", rotation.device_token);
          setDeviceTokenValue(rotation.device_token);
        } else if (msg.type === "error") {
          setIsMatching(false);
          const err = msg as ErrorMessage;
          
          if (err.error.code === "RATE_LIMITED") {
            // Silently ignore device-level burst rate limits to avoid annoying the user
            return;
          }
          
          if (err.error.code === "COOLDOWN_ACTIVE") {
            // Treat cooldown as a friendly reminder rather than an error
            logMessage(`Match result: You are already checked in.`, "info");
            setScanInfo("You are already checked in.");
            setTimeout(() => setScanInfo(null), 3000);
            return;
          }

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

  // Memoize scan gating settings from server-pushed configs or relaxed defaults
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
    const s: Record<string, number> = {};
    const addIfDefined = (key: string, targetKey: string) => {
      const val = kioskSettings[key];
      if (val !== undefined && val !== null) {
        s[targetKey] = val as number;
      }
    };
    addIfDefined("kiosk.gate.min_bbox_area_pct", "min_bbox_area_pct");
    addIfDefined("kiosk.gate.min_interocular_px", "min_interocular_px");
    addIfDefined("kiosk.gate.max_center_offset_pct", "max_center_offset_pct");
    addIfDefined("kiosk.gate.min_sharpness", "min_sharpness");
    addIfDefined("kiosk.gate.luma_min", "luma_min");
    addIfDefined("kiosk.gate.luma_max", "luma_max");
    addIfDefined("kiosk.gate.stability_iou", "stability_iou");
    addIfDefined("kiosk.gate.stability_frames", "stability_frames");
    addIfDefined("kiosk.gate.stability_ms", "stability_ms");
    addIfDefined("kiosk.burst_count", "burst_count");
    addIfDefined("kiosk.burst_interval_ms", "burst_interval_ms");
    return s;
  }, [relaxedGating, kioskSettings]);

  // Initialize scan loop hook
  const { isLoadingModel, isScanRunning, resetLockout, detectedBbox, reason, metrics, cameraError, modelError } = useScanLoop({
    videoRef,
    isScanActive: activeScan && wsStatus === "connected" && !scanResult && !showEnroll,
    isAppBackgrounded: isAppBackgrounded,
    facingMode: facingMode,
    scanMode: (kioskSettings["kiosk.scan_mode"] as "continuous" | "tap_to_scan" | undefined) ?? "continuous",
    settings: scanSettings,
    onBurstCaptured: handleBurstCaptured,
    onGatingFailed: handleGatingFailed,
    onGatingPassed: () => setGatingStatus("Perfect! Checking face..."),
    onDetected: () => playBeep(520, "sine", 0.05),
  });

  // Replay queued offline scans
  const replayOfflineScans = async () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        const scans = await getOfflineScans();
        if (scans.length === 0) return;
        logMessage(`Replaying ${scans.length} queued offline scans...`, "info");
        for (const scan of scans) {
          let elapsed = performance.now() - scan.captured_at_perf;
          if (elapsed < 0 || performance.now() < scan.captured_at_perf) {
            // Browser reloaded: absolute wall clock fallback
            elapsed = Date.now() - new Date(scan.occurred_at_iso).getTime();
          }
          const finalOffset = Math.max(0, Math.round(elapsed));
          const payload = {
            type: "check_in",
            external_id: scan.external_id,
            idempotency_key: scan.idempotency_key,
            direction: scan.direction,
            monotonic_offset_ms: finalOffset
          };
          wsRef.current.send(JSON.stringify(payload));
          await removeOfflineScan(scan.idempotency_key);
        }
        setQueueDepth(await getOfflineQueueDepth());
        logMessage("All offline scans replayed successfully.", "info");
      } catch (err) {
        logMessage(`Failed to replay offline scans: ${err}`, "error");
      }
    }
  };

  // PIN / QR Fallback scan functionality
  const sendCheckIn = async (externalId: string) => {
    const idempotencyKey = crypto.randomUUID();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const payload = {
        type: "check_in",
        external_id: externalId,
        idempotency_key: idempotencyKey,
        direction: "in",
        monotonic_offset_ms: 0
      };
      logMessage(`Sending manual check-in request (external_id: ${externalId}, idempotency_key: ${idempotencyKey})`, "info");
      setIsMatching(true);
      setScanError(null);
      wsRef.current.send(JSON.stringify(payload));
    } else {
      logMessage(`Kiosk is offline. Queuing check-in request locally (external_id: ${externalId}, idempotency_key: ${idempotencyKey})`, "info");
      try {
        await enqueueOfflineScan({
          idempotency_key: idempotencyKey,
          external_id: externalId,
          direction: "in"
        });
        setQueueDepth(await getOfflineQueueDepth());
        setScanInfo("Offline: Scan queued in local database.");
        setTimeout(() => setScanInfo(null), 3000);
      } catch (err) {
        logMessage(`Failed to queue offline scan: ${err}`, "error");
        setScanError("Failed to store check-in offline.");
        setTimeout(() => setScanError(null), 4000);
      }
    }
  };

  const handlePinSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (pinValue.trim()) {
      sendCheckIn(pinValue.trim());
      setPinValue("");
    }
  };

  const handleKeypadPress = (val: string) => {
    setPinValue((prev) => prev + val);
  };

  const handleKeypadClear = () => {
    setPinValue("");
  };

  const handleKeypadBackspace = () => {
    setPinValue((prev) => prev.slice(0, -1));
  };

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
    if (reason.includes("invalid_luma") && metrics && metrics.luma !== null && metrics.luma !== undefined) {
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
    <main className="relative min-h-screen bg-canvas font-sans text-white antialiased">
      <header className="mx-6 mt-6 bg-surface-card/60 backdrop-blur-md border border-hairline rounded-2xl px-6 py-4 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-xl shadow-black/30 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-1.5 w-8 rounded-full overflow-hidden select-none">
            <div className="w-1/3 bg-m-blue-light" />
            <div className="w-1/3 bg-m-blue-dark" />
            <div className="w-1/3 bg-m-red" />
          </div>
          <span className="font-bold tracking-wider text-sm text-zinc-100 font-sans">{(kioskSettings["branding.org_name"] as string | undefined) || "Aegis Biometrics"}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 md:gap-3">
          {/* Offline Queue Depth Badge */}
          {queueDepth > 0 && (
            <div className="flex items-center gap-2 rounded-full bg-amber-950/30 text-amber-400 border border-amber-800/40 px-3.5 py-1 text-xs font-semibold tracking-wide animate-pulse">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{queueDepth} Offline scan{queueDepth === 1 ? "" : "s"} queued</span>
            </div>
          )}
 
          {/* WS Status Indicator */}
          <div 
            onClick={() => {
              if (wsStatus === "disconnected" || !!(window as any).Capacitor) {
                setIsConnModalOpen(true);
              }
            }}
            className={`flex items-center gap-2 rounded-xl bg-surface-soft px-3.5 py-1.5 text-xs font-semibold tracking-wide border border-hairline text-zinc-300 ${wsStatus === "disconnected" || !!(window as any).Capacitor ? 'cursor-pointer hover:border-zinc-400 transition-colors' : ''}`}
            title="Click to configure connection URL"
          >
            {wsStatus === "connected" ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                <span>Connected</span>
              </>
            ) : wsStatus === "connecting" ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse shadow-[0_0_8px_rgba(245,158,11,0.6)]" />
                <span>Connecting</span>
              </>
            ) : (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.6)]" />
                <span>Disconnected</span>
              </>
            )}
          </div>
 
          {/* Mode Badge + Toggle */}
          <div className="flex items-center">
            <button
              onClick={() => {
                const enteringEnroll = !showEnroll;
                setShowEnroll(enteringEnroll);
                setEnrollSuccess(null);
                setEnrollError(null);
                setActiveScan(!enteringEnroll);
              }}
              className="rounded-xl border border-hairline bg-surface-soft text-zinc-300 hover:text-white px-3.5 py-1.5 text-xs font-semibold tracking-wide hover:bg-surface-elevated transition-all active:scale-[0.96]"
              title={showEnroll ? "Click to switch to Scan Mode" : "Click to switch to Registration Mode"}
            >
              {showEnroll ? "Registration Mode" : "Scan Mode"}
            </button>
          </div>

          {/* Camera Facing mode toggle */}
          <button
            onClick={() => setFacingMode(prev => prev === "user" ? "environment" : "user")}
            className="rounded-xl border border-hairline bg-surface-soft text-zinc-300 hover:text-white px-3.5 py-1.5 text-xs font-semibold tracking-wide hover:bg-surface-elevated transition-all active:scale-[0.96]"
            title="Toggle Front/Back Camera"
          >
            Camera: {facingMode === "user" ? "Front" : "Back"}
          </button>

          {/* iOS Capacitor Mobile Admin Panel Launcher */}
          {!!(window as any).Capacitor && (
            <button
              onClick={() => {
                const serverUrl = apiBaseUrl || window.location.origin;
                const adminUrl = serverUrl.replace(":8001", ":5174").replace("/api", "");
                window.location.href = adminUrl;
              }}
              className="rounded-xl border border-m-blue-dark/50 bg-m-blue-dark/10 text-m-blue-light px-3.5 py-1.5 text-xs font-semibold tracking-wide hover:bg-m-blue-dark hover:text-white transition-all active:scale-[0.96]"
              title="Launch Admin Console"
            >
              Admin Console
            </button>
          )}
 
          {wsStatus === "disconnected" && (
            <button
              onClick={fetchToken}
              className="rounded-xl bg-primary hover:bg-primary/95 text-white px-4 py-1.5 text-xs font-bold tracking-wider hover:shadow-lg hover:shadow-primary/10 transition-all active:scale-[0.96]"
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
                  setShowEnroll(false);
                }
              }}
              className="rounded-xl border border-primary text-primary hover:bg-primary hover:text-white px-3.5 py-1.5 text-xs font-semibold tracking-wide transition-all active:scale-[0.96]"
            >
              {activeScan ? 'Stop Scanning' : 'Start Scanning'}
            </button>
          )}
        </div>
      </header>

      <section className={`mx-auto grid max-w-5xl gap-8 px-6 py-12 ${import.meta.env.DEV ? "md:grid-cols-3" : "md:grid-cols-1 justify-center max-w-2xl"}`}>
        {/* Left Side: Scan Feed and Centering Overlays */}
        <div className={import.meta.env.DEV ? "md:col-span-2 flex flex-col gap-4" : "flex flex-col gap-4"}>
          <div className="relative aspect-[4/3] rounded-2xl overflow-hidden border border-hairline bg-black shadow-xl shadow-black/40">
            {/* Live Camera Feed */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="h-full w-full object-cover transform scale-x-[-1]"
            />

            {/* Camera/Model Error Warning Banners */}
            {(cameraError || modelError) && (
              <div className="absolute top-4 left-4 right-4 bg-rose-950/85 border border-rose-800/40 text-rose-300 text-[10px] uppercase font-bold tracking-wider px-4 py-3 rounded-xl z-20 shadow-lg backdrop-blur-sm flex items-center gap-3">
                <svg className="h-4.5 w-4.5 text-rose-400 shrink-0 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <span>{cameraError || modelError}</span>
              </div>
            )}

            {/* Glowing Laser Scan Bar */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-primary to-transparent opacity-85 shadow-[0_0_12px_rgba(99,102,241,0.8)] animate-scan-line pointer-events-none" />
            )}

            {/* Face centering guide target */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="h-60 w-60 rounded-full border-2 border-dashed border-primary/30 flex items-center justify-center animate-[spin_40s_linear_infinite]">
                  <div className="h-52 w-52 rounded-full border border-primary/10 shadow-[0_0_15px_rgba(99,102,241,0.05)]" />
                </div>
              </div>
            )}

            {/* Flash Effect on Capture */}
            {isMatching && (
              <div className="absolute inset-0 bg-white pointer-events-none animate-camera-flash z-10" />
            )}

            {/* Processing Identity Overlay */}
            {isMatching && (
              <div className="absolute inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center pointer-events-none z-20">
                <div className="flex flex-col items-center gap-4">
                  <div className="relative h-16 w-16">
                    <div className="absolute inset-0 rounded-full border-4 border-white/10" />
                    <div className="absolute inset-0 rounded-full border-4 border-primary border-t-transparent animate-spin" />
                  </div>
                  <span className="text-white font-mono text-xs tracking-[0.2em] font-bold animate-pulse shadow-black drop-shadow-md">
                    PROCESSING BIOMETRICS
                  </span>
                </div>
              </div>
            )}

            {/* Enrollment Guide Overlay */}
            {isScanRunning && showEnroll && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none bg-black/40">
                {/* Face Silhouette Guide */}
                <div className="h-64 w-48 rounded-[120px] border-2 border-dashed border-primary shadow-[0_0_20px_rgba(99,102,241,0.3)] flex items-center justify-center animate-[pulse_2s_infinite]">
                  <div className="h-56 w-40 rounded-[100px] border border-primary/20" />
                </div>
                {/* Text guide */}
                <div className="absolute bottom-6 bg-surface-card border border-hairline rounded-xl px-4 py-2 text-xs text-white font-bold tracking-wide shadow-lg">
                  Position your face and click "Capture & Register"
                </div>
              </div>
            )}

            {/* Disconnected Overlay */}
            {wsStatus !== "connected" && !isLoadingModel && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-canvas/95 backdrop-blur-md z-10 p-6 text-center">
                <div className="w-16 h-16 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-500 flex items-center justify-center mb-4">
                  <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-3.536 4.978 4.978 0 011.414-3.536m0 0L8.464 8.464M5.636 5.636a9 9 0 000 12.728m0 0L3 21" />
                  </svg>
                </div>
                <p className="text-white text-sm font-bold tracking-wider uppercase mb-1">Kiosk Offline</p>
                <p className="text-muted-color text-xs tracking-wide font-light mb-6">Set up the API connection or click connect to begin</p>
                <div className="flex flex-col gap-2 w-full max-w-xs z-20">
                  <button
                    onClick={fetchToken}
                    className="w-full bg-primary hover:bg-primary/90 text-white py-2.5 rounded-xl uppercase tracking-widest text-[10px] font-bold transition-all shadow-lg shadow-primary/10 active:scale-[0.96]"
                  >
                    Connect Kiosk
                  </button>
                  <button
                    onClick={() => setIsConnModalOpen(true)}
                    className="w-full bg-surface-soft text-zinc-300 border border-hairline py-2.5 rounded-xl uppercase tracking-widest text-[10px] font-bold hover:text-white hover:border-zinc-400 transition-all active:scale-[0.96]"
                  >
                    Server Settings
                  </button>
                </div>
              </div>
            )}

            {/* Scan Mode Active Indicator */}
            {isScanRunning && wsStatus === "connected" && !scanResult && !showEnroll && (
              <div className="absolute top-4 left-4 bg-canvas/80 border border-hairline rounded-full px-3 py-1.5 text-[10px] text-white font-bold tracking-wide z-10 flex items-center gap-1.5 shadow-lg shadow-black/80 backdrop-blur-sm">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse shadow-[0_0_6px_rgba(244,63,94,0.6)]" />
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
                className={`absolute border-2 rounded-xl transition-all duration-75 pointer-events-none ${
                  showEnroll 
                    ? "border-white shadow-[0_0_8px_rgba(255,255,255,0.4)]" 
                    : reason 
                    ? "border-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.4)]" 
                    : "border-primary shadow-[0_0_8px_rgba(99,102,241,0.4)]"
                }`}
              >
                <div className={`absolute -top-7 left-0 px-2.5 py-1 rounded-full text-[9px] font-bold text-white uppercase tracking-wider whitespace-nowrap shadow-md ${
                  showEnroll 
                    ? "bg-zinc-600" 
                    : reason 
                    ? "bg-amber-500" 
                    : "bg-primary"
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
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-canvas/80 backdrop-blur-[2px] z-10 animate-fade-in">
                <div className="relative h-28 w-28 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border-4 border-white/10 border-t-white animate-spin" />
                  <svg className="h-10 w-10 text-white animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <p className="text-white text-xs font-bold tracking-widest uppercase mt-4 animate-pulse">
                  Analyzing Biometrics
                </p>
                <p className="text-muted-color text-[10px] uppercase tracking-wider mt-1">
                  Matching face against gallery...
                </p>
              </div>
            )}
 
            {/* Loading / Startup Overlay */}
            {isLoadingModel && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-canvas/95 backdrop-blur-sm z-10">
                <div className="h-10 w-10 border-4 border-primary/20 border-t-primary rounded-full animate-spin mb-4" />
                <p className="text-zinc-400 text-xs font-semibold tracking-wide">Loading Face Engine WASM Models...</p>
              </div>
            )}
 
            {/* Attendance Punch Result Notification Modal */}
            {scanResult && scanResult.person && (
              <div className="absolute inset-0 flex items-center justify-center bg-canvas/90 backdrop-blur-md z-20 animate-fade-in">
                <div className="flex flex-col items-center text-center p-8 max-w-sm rounded-2xl bg-surface-card/90 border border-hairline shadow-2xl animate-scale-up backdrop-blur-md">
                  <div className="h-20 w-20 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-5 animate-pulse">
                    <svg className="h-10 w-10 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-bold tracking-wide text-white mb-2">Punch Success</h3>
                  <p className="text-white text-base font-semibold mb-1">{scanResult.person.display_name}</p>
                  <p className="text-zinc-400 text-[10px] font-semibold uppercase tracking-wider mb-4">
                    {scanResult.direction === "in" ? "CHECK-IN" : "CHECK-OUT"} • {new Date(scanResult.occurred_at).toLocaleTimeString()}
                  </p>
                  <span className="text-[10px] text-zinc-300 bg-surface-soft border border-hairline rounded-full px-3 py-1.5 uppercase font-semibold tracking-wide">
                    Attendance Logged
                  </span>
                </div>
              </div>
            )}
 
            {/* Gating Error Notification */}
            {scanError && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-rose-950/95 border border-rose-800/40 backdrop-blur-md rounded-full px-5 py-3 shadow-2xl z-20 animate-scale-up">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-pulse shadow-[0_0_6px_rgba(244,63,94,0.6)]" />
                <span className="text-rose-200 text-xs font-semibold tracking-wide">{scanError}</span>
              </div>
            )}
 
            {/* Friendly Info Notification */}
            {scanInfo && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-zinc-900/95 border border-hairline backdrop-blur-md rounded-full px-5 py-3 shadow-2xl z-20 animate-scale-up">
                <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse shadow-[0_0_6px_rgba(255,255,255,0.6)]" />
                <span className="text-white text-xs font-semibold tracking-wide">{scanInfo}</span>
              </div>
            )}
          </div>
 
          {/* Real-time scanning ticker / Gating feedback */}
          <div className="flex items-center gap-3.5 rounded-2xl border border-hairline bg-surface-soft px-5 py-3.5 text-xs text-zinc-400 font-semibold tracking-wide shadow-md">
            <span className={`h-1.5 w-1.5 rounded-full ${wsStatus === "connected" && isScanRunning ? "bg-primary animate-pulse shadow-[0_0_6px_rgba(99,102,241,0.6)]" : "bg-hairline"}`} />
            <span>{gatingStatus}</span>
            {isScanRunning && wsStatus === "connected" && (
              <button
                onClick={resetLockout}
                className="ml-auto text-[10px] font-semibold tracking-wide text-zinc-300 border border-hairline hover:border-zinc-400 bg-transparent px-2.5 py-1 rounded-xl transition-all active:scale-[0.96] hover:bg-surface-elevated"
              >
                Reset Lockout
              </button>
            )}
          </div>
          {/* Face Enrollment Card (Visible when Registration Mode is active) */}
          {showEnroll && (
            <div className="rounded-2xl border border-hairline bg-surface-card p-6 shadow-xl shadow-black/10 animate-scale-up">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xs font-bold uppercase tracking-widest text-white">Enroll Face Profile</h2>
                <span className="text-[9px] bg-surface-soft text-zinc-400 border border-hairline px-2.5 py-0.5 rounded-full uppercase font-mono tracking-wider font-bold">Biometrics</span>
              </div>
              
              <p className="text-xs text-zinc-400 mb-6 font-light">
                Enter the name below, position your face in the camera frame, and click "Capture & Register".
              </p>

              <div className="space-y-4">
                <div>
                  <label htmlFor="enroll-name" className="block text-[10px] font-bold text-white uppercase tracking-wider mb-2">
                    Person Name
                  </label>
                  <input
                    id="enroll-name"
                    type="text"
                    placeholder="e.g. Alice Cooper"
                    value={enrollName}
                    onChange={(e) => setEnrollName(e.target.value)}
                    disabled={isEnrolling}
                    className="w-full rounded-xl bg-surface-soft border border-hairline px-4 py-2.5 text-xs text-white placeholder-zinc-600 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all font-medium"
                  />
                </div>

                <button
                  onClick={enrollFace}
                  disabled={isEnrolling || !enrollName.trim()}
                  className="w-full bg-primary hover:bg-primary/90 text-white font-bold py-2.5 text-xs uppercase tracking-widest transition-all flex items-center justify-center gap-2 rounded-xl disabled:bg-surface-soft disabled:text-zinc-600 disabled:shadow-none active:scale-[0.97] shadow-lg shadow-primary/20"
                >
                  {isEnrolling ? (
                    <>
                      <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      Registering Biometrics...
                    </>
                  ) : (
                    "Capture & Register"
                  )}
                </button>

                {enrollSuccess && (
                  <div className="rounded-xl bg-emerald-950/20 border border-emerald-800/40 p-3 text-xs text-emerald-400 font-semibold tracking-wide">
                    {enrollSuccess}
                  </div>
                )}

                {enrollError && (
                  <div className="rounded-xl bg-rose-950/20 border border-rose-800/40 p-3 text-xs text-rose-400 font-semibold tracking-wide">
                    {enrollError}
                  </div>
                )}
              </div>

              {/* List of current registrations */}
              <div className="mt-6 pt-6 border-t border-hairline space-y-3">
                <div className="flex justify-between items-center">
                  <h3 className="text-[10px] font-bold text-white uppercase tracking-wider">
                    Current Registered Profiles ({people.length})
                  </h3>
                  {people.length > 0 && (
                    <button
                      onClick={deleteAllPeople}
                      className="text-[9px] text-rose-400 hover:text-rose-300 font-bold uppercase tracking-wider transition-colors"
                    >
                      Delete All
                    </button>
                  )}
                </div>
                
                <div className="max-h-48 overflow-y-auto space-y-2 scrollbar-thin pr-1">
                  {people.length === 0 ? (
                    <p className="text-[10px] text-zinc-500 uppercase tracking-wider py-4 text-center font-bold">No registered profiles found.</p>
                  ) : (
                    people.map((person) => (
                      <div key={person.id} className="flex justify-between items-center bg-surface-soft border border-hairline rounded-xl px-3.5 py-2.5 hover:border-zinc-400 transition-all">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs font-bold text-white uppercase tracking-wider">{person.display_name}</span>
                          <span className="text-[9px] text-muted-color uppercase font-mono">{person.id.slice(0, 8)}... • {person.kind}</span>
                        </div>
                        <button
                          onClick={() => deletePerson(person.id, person.display_name)}
                          className="text-[9px] text-rose-500 hover:text-rose-400 font-bold uppercase tracking-wider transition-colors animate-scale-up"
                        >
                          Delete
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          {/* PIN / QR Code Fallback Card */}
          <div className="rounded-2xl border border-hairline bg-surface-card p-6 shadow-xl shadow-black/10">
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-xs font-bold uppercase tracking-widest text-white">PIN / QR Code Fallback</h2>
                  <span className="text-[9px] bg-surface-soft text-zinc-400 border border-hairline px-2.5 py-0.5 rounded-full uppercase font-mono tracking-wider font-bold">Accessibility</span>
                </div>
                
                <p className="text-xs text-zinc-400 font-light">
                  Type your ID/PIN or position your QR code in front of the camera (simulated via text input).
                </p>
 
                {/* Input with inline submit */}
                <form onSubmit={handlePinSubmit} className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Enter your PIN or Scan QR Code..."
                    value={pinValue}
                    onChange={(e) => setPinValue(e.target.value)}
                    disabled={isMatching}
                    className="flex-1 rounded-xl bg-surface-soft border border-hairline px-4 py-2.5 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all"
                  />
                  <button
                    type="submit"
                    disabled={isMatching || !pinValue.trim()}
                    className="bg-primary hover:bg-primary/90 text-white font-bold px-5 py-2.5 rounded-xl transition-all text-xs uppercase tracking-widest disabled:bg-surface-soft disabled:text-zinc-600 disabled:border-none disabled:shadow-none active:scale-[0.96]"
                  >
                    Check In
                  </button>
                </form>
 
                {/* Tactile Touchscreen Keypad */}
                <div className="grid grid-cols-3 gap-2 max-w-xs mx-auto w-full pt-2">
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((num) => (
                    <button
                      key={num}
                      type="button"
                      onClick={() => handleKeypadPress(num.toString())}
                      disabled={isMatching}
                      className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-white font-semibold py-3.5 rounded-xl border border-hairline transition-all text-sm select-none"
                    >
                      {num}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={handleKeypadClear}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-rose-500 font-semibold py-3.5 rounded-xl border border-hairline transition-all text-sm select-none"
                  >
                    Clear
                  </button>
                  <button
                    type="button"
                    onClick={() => handleKeypadPress("0")}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-white font-semibold py-3.5 rounded-xl border border-hairline transition-all text-sm select-none"
                  >
                    0
                  </button>
                  <button
                    type="button"
                    onClick={handleKeypadBackspace}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-white font-semibold py-3.5 rounded-xl border border-hairline transition-all text-sm flex items-center justify-center select-none"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3 12l6.414-6.414A2 2 0 0010.828 5H20a2 2 0 012 2v10a2 2 0 01-2 2h-9.172a2 2 0 01-1.414-.586L3 12z" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>

        {/* Right Side: Setup instructions and Dev Tools */}
        {import.meta.env.DEV && (
          <div className="flex flex-col gap-6">
            <div className="rounded-2xl border border-hairline bg-surface-card p-6 shadow-xl shadow-black/10">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xs font-bold uppercase tracking-widest text-white">Local Dev Tools</h2>
                <span className="text-[9px] bg-surface-soft text-zinc-400 border border-hairline px-2 py-0.5 rounded-full uppercase font-mono tracking-wider font-bold">Ready</span>
              </div>
              
              <p className="text-xs text-zinc-400 mb-6 font-light">
                Use this shortcut to easily seed new profiles directly via your webcam, enabling local matching scans.
              </p>
 
              {/* Relax scan criteria toggle */}
              <div className="flex items-center justify-between bg-surface-soft border border-hairline rounded-2xl px-4 py-3 mb-4 select-none">
                <div className="flex flex-col gap-0.5 pr-2">
                  <span className="text-xs font-bold text-white uppercase tracking-wider">Relax Scan Criteria</span>
                  <span className="text-[9px] text-muted-color uppercase tracking-wider mt-0.5 font-light">Bypasses strict distance/lighting gates</span>
                </div>
                <button
                  onClick={() => setRelaxedGating(!relaxedGating)}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ${
                    relaxedGating ? "bg-primary" : "bg-zinc-700"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ${
                      relaxedGating ? "translate-x-4.5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>

            </div>
            
            {/* Real-time Logs Console */}
            <div className="rounded-2xl border border-hairline bg-surface-card p-6 flex flex-col h-80 shadow-xl shadow-black/10">
              <div className="flex justify-between items-center mb-3 border-b border-hairline pb-2">
                <h2 className="text-xs font-bold uppercase tracking-widest text-white">Live Connection Logs</h2>
                <button
                  onClick={() => setLogs([])}
                  className="text-[10px] text-zinc-400 hover:text-white bg-surface-soft px-3 py-1 rounded-xl border border-hairline transition-all uppercase tracking-wider font-bold active:scale-95"
                >
                  Clear Logs
                </button>
              </div>
              <div className="flex-1 overflow-y-auto font-mono text-[9px] text-zinc-400 space-y-1.5 p-3 rounded-xl bg-surface-soft border border-hairline select-text scrollbar-thin">
                {logs.length === 0 ? (
                  <p className="text-muted-color italic uppercase text-center py-4">No logs recorded yet.</p>
                ) : (
                  logs.map((log, idx) => (
                    <div
                      key={idx}
                      className={
                        log.includes("ERROR:") || log.includes("failed") || log.includes("closed")
                          ? "text-red-400 font-bold uppercase tracking-wider"
                          : log.includes("success") || log.includes("Success") || log.includes("opened")
                          ? "text-emerald-400 font-bold uppercase tracking-wider"
                          : "text-body-strong font-light"
                      }
                    >
                      {log}
                    </div>
                  ))
                )}
              </div>
            </div>
 
            {/* Quickstart Reference Box */}
            <div className="rounded-2xl border border-hairline bg-surface-card p-6 space-y-4 shadow-xl shadow-black/10">
              <h3 className="text-[10px] font-bold uppercase tracking-widest text-white border-b border-hairline pb-2">Step-by-step Test</h3>
              <ol className="list-decimal list-inside space-y-2.5 text-xs text-body-color font-light">
                <li>Click <span className="text-white font-bold uppercase tracking-wider">Connect Kiosk</span> to connect the WebSocket to the local backend.</li>
                <li>Click <span className="text-white font-bold uppercase tracking-wider">Enroll Face Profile</span>, enter your name, and click <span className="text-white font-bold uppercase tracking-wider">Capture & Register</span>.</li>
                <li>Wait for the green success confirmation card (it will auto-close in 3s).</li>
                <li>In <strong className="font-bold text-white uppercase tracking-wider">Scan Mode</strong> (when enrollment is closed), look directly at the webcam inside the scanning circle.</li>
                <li>The app will automatically match your face and display a green <strong className="font-bold text-white uppercase tracking-wider">"Punch Success"</strong> card!</li>
              </ol>
            </div>
          </div>
        )}
      </section>
      <ConnectionSettingsModal
          isOpen={isConnModalOpen}
          onClose={() => setIsConnModalOpen(false)}
          currentUrl={apiUrl}
          onSave={async (url, pairingCode) => {
            let formatted = url.trim();
            if (formatted && !/^https?:\/\//i.test(formatted)) {
              formatted = `http://${formatted}`;
            }
            if (formatted.endsWith("/")) {
              formatted = formatted.slice(0, -1);
            }
            localStorage.setItem("aegis_api_url", formatted);
            setApiUrl(formatted);

            if (pairingCode) {
              logMessage(`Attempting device pairing with code: ${pairingCode}...`, "info");
              try {
                const pairRes = await fetch(`${formatted}/api/kiosk/pair`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ pairing_code: pairingCode }),
                });
                if (!pairRes.ok) {
                  const errorData = await pairRes.json().catch(() => ({}));
                  const detailMsg = errorData.detail?.error?.message || `HTTP ${pairRes.status}`;
                  throw new Error(`Pairing failed: ${detailMsg}`);
                }
                const pairData = await pairRes.json();
                localStorage.setItem("aegis_device_token", pairData.device_token);
                localStorage.setItem("aegis_device_id", pairData.device_id);
                setDeviceTokenValue(pairData.device_token);
                setDeviceId(pairData.device_id);
                logMessage("Device paired successfully! Connecting to scanner...", "info");
              } catch (pairErr: any) {
                logMessage(pairErr.message || "Pairing failed", "error");
                setWsStatus("disconnected");
                setWsError(pairErr.message || "Device pairing failed");
                return;
              }
            } else {
              logMessage(`Updated API URL to ${formatted}. Reconnecting...`, "info");
            }

            if (wsRef.current) {
              wsRef.current.close();
            } else {
              // Trigger a token fetch/connection manually if WS isn't active
              fetchToken();
            }
          }}
        />
      </main>
  );
}
