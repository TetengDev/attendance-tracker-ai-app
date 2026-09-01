import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
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

export function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  
  // Dynamic API configuration
  const [apiUrl, setApiUrl] = useState(() => {
    const saved = localStorage.getItem("aegis_api_url");
    if (saved && !saved.includes(":8000")) {
      return saved;
    }
    return defaultApiBaseUrl;
  });
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
  const [showSettings, setShowSettings] = useState(false);
  const [activeTab, setActiveTab] = useState<'scan' | 'pin'>('scan');

  useEffect(() => {
    if (wsStatus === "connected") {
      setActiveTab("scan");
    } else if (wsStatus === "disconnected") {
      setActiveTab("pin");
    }
  }, [wsStatus]);
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
    isScanActive: activeScan && wsStatus === "connected" && !scanResult && !showEnroll && activeTab === "scan",
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
    <main className="relative min-h-screen bg-canvas font-sans text-white antialiased flex flex-col justify-between overflow-x-hidden">
      {/* Header */}
      <header className="mx-6 mt-6 bg-surface-card/60 backdrop-blur-md border border-hairline rounded-2xl px-6 py-4 flex items-center justify-between shadow-xl shadow-black/30 shrink-0 select-none">
        <div className="flex items-center gap-3">
          <div className="flex h-1.5 w-8 rounded-full overflow-hidden">
            <div className="w-1/3 bg-primary" />
            <div className="w-1/3 bg-emerald-500" />
            <div className="w-1/3 bg-rose-500" />
          </div>
          <span className="font-bold tracking-wider text-sm text-zinc-100 uppercase">
            {(kioskSettings["branding.org_name"] as string | undefined) || "Aegis Kiosk"}
          </span>
        </div>
        
        <div className="flex items-center gap-3.5">
          {/* Offline Sync Indicator */}
          {queueDepth > 0 && (
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="flex items-center gap-1.5 rounded-full bg-amber-950/40 text-amber-400 border border-amber-800/30 px-3 py-1 text-[10px] font-bold uppercase tracking-wider animate-pulse"
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{queueDepth} Pending</span>
            </motion.div>
          )}

          {/* Status badge */}
          <div className="flex items-center gap-2 rounded-xl bg-surface-soft px-3 py-1.5 border border-hairline text-[10px] uppercase font-bold tracking-wider text-zinc-400">
            {wsStatus === "connected" ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse" />
                <span>Online</span>
              </>
            ) : wsStatus === "connecting" ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)] animate-pulse" />
                <span>Connecting</span>
              </>
            ) : (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]" />
                <span>Offline</span>
              </>
            )}
          </div>

          {/* Admin Toggle (Gear Icon) */}
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-xl border border-hairline transition-all ${
              showSettings
                ? "bg-primary border-primary text-white shadow-lg shadow-primary/20"
                : "bg-surface-soft text-zinc-400 hover:text-white hover:bg-surface-elevated"
            }`}
            title="Admin Settings"
          >
            <svg className="w-4.5 h-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </motion.button>
        </div>
      </header>

      {/* Main Content Area */}
      <section className="flex-1 flex flex-col justify-center items-center px-6 py-8 relative">
        
        {/* Offline Banner Indicator */}
        {wsStatus === "disconnected" && !showSettings && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full max-w-sm bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs rounded-2xl px-4 py-3.5 text-center mb-6 font-bold uppercase tracking-wider flex items-center justify-center gap-2 animate-pulse"
          >
            <span className="h-1.5 w-1.5 bg-rose-500 rounded-full animate-ping" />
            Offline Mode — Punching with PIN
          </motion.div>
        )}

        {/* Tab Switcher */}
        {wsStatus === "connected" && !showSettings && (
          <div className="relative flex bg-surface-soft border border-hairline rounded-2xl p-1 mb-8 w-full max-w-[260px] select-none shadow-lg">
            <button
              onClick={() => setActiveTab("scan")}
              className="relative flex-1 py-2 text-[10px] font-bold uppercase tracking-widest text-center focus:outline-none"
            >
              <span className={`relative z-10 transition-colors duration-200 ${activeTab === 'scan' ? 'text-white' : 'text-zinc-500'}`}>Face Scan</span>
              {activeTab === 'scan' && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute inset-0 bg-primary rounded-xl"
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                />
              )}
            </button>
            <button
              onClick={() => setActiveTab("pin")}
              className="relative flex-1 py-2 text-[10px] font-bold uppercase tracking-widest text-center focus:outline-none"
            >
              <span className={`relative z-10 transition-colors duration-200 ${activeTab === 'pin' ? 'text-white' : 'text-zinc-500'}`}>Enter PIN</span>
              {activeTab === 'pin' && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute inset-0 bg-primary rounded-xl"
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          </div>
        )}

        {/* Viewport for Active Tab */}
        {!showSettings && (
          <div className="w-full max-w-md flex flex-col items-center justify-center">
            
            {/* FACE SCAN VIEW */}
            {activeTab === "scan" && wsStatus === "connected" && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center w-full"
              >
                <div className="relative w-72 h-72 rounded-full overflow-hidden border-4 border-hairline-strong bg-black shadow-2xl shadow-black/80 flex items-center justify-center">
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="h-full w-full object-cover transform scale-x-[-1]"
                  />

                  {/* Laser Scan Line */}
                  {isScanRunning && !scanResult && !showEnroll && (
                    <div className="absolute left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-primary to-transparent opacity-85 shadow-[0_0_12px_rgba(99,102,241,0.8)] animate-scan-line pointer-events-none" />
                  )}

                  {/* Target Guide Ring */}
                  {isScanRunning && !scanResult && !showEnroll && (
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                      <div className="h-56 w-56 rounded-full border-2 border-dashed border-primary/30 flex items-center justify-center animate-[spin_40s_linear_infinite]" />
                    </div>
                  )}

                  {/* Camera Flash */}
                  {isMatching && (
                    <div className="absolute inset-0 bg-white pointer-events-none animate-camera-flash z-10" />
                  )}

                  {/* Processing Biometrics */}
                  {isMatching && (
                    <div className="absolute inset-0 bg-black/80 backdrop-blur-sm flex flex-col items-center justify-center z-20">
                      <div className="h-10 w-10 border-4 border-primary border-t-transparent rounded-full animate-spin mb-3" />
                      <span className="text-[10px] text-zinc-300 uppercase tracking-widest font-bold animate-pulse">
                        Matching Biometrics...
                      </span>
                    </div>
                  )}

                  {/* Loading/Startup Overlay */}
                  {isLoadingModel && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-canvas/95 backdrop-blur-sm z-10">
                      <div className="h-8 w-8 border-4 border-primary/20 border-t-primary rounded-full animate-spin mb-3" />
                      <p className="text-zinc-500 text-[10px] uppercase tracking-widest font-bold">Initializing Engine...</p>
                    </div>
                  )}

                  {/* Live Camera Warnings */}
                  {(cameraError || modelError) && (
                    <div className="absolute inset-x-4 top-4 bg-rose-950/90 border border-rose-800/40 text-rose-300 text-[9px] uppercase font-bold tracking-wider px-3.5 py-2.5 rounded-xl z-20 text-center">
                      {cameraError || modelError}
                    </div>
                  )}

                  {/* Gating Bounding Box Overlay */}
                  {isScanRunning && !scanResult && detectedBbox && (
                    <div
                      style={{
                        left: `${100 - detectedBbox.x - detectedBbox.w}%`,
                        top: `${detectedBbox.y}%`,
                        width: `${detectedBbox.w}%`,
                        height: `${detectedBbox.h}%`,
                      }}
                      className={`absolute border-2 rounded-xl transition-all duration-75 pointer-events-none ${
                        reason ? "border-amber-500" : "border-primary"
                      }`}
                    >
                      <div className={`absolute -top-6 left-0 px-2 py-0.5 rounded-full text-[8px] font-bold text-white uppercase tracking-wider whitespace-nowrap shadow-md ${
                        reason ? "bg-amber-500" : "bg-primary"
                      }`}>
                        {reason ? getGatingInstruction() : "Scanning..."}
                      </div>
                    </div>
                  )}
                </div>

                {/* Instructions text */}
                <div className="text-center mt-6 select-none animate-pulse">
                  <h2 className="text-base font-bold text-white uppercase tracking-wider">Ready to Scan</h2>
                  <p className="text-zinc-500 text-xs mt-1 font-light">Look at the camera to check in</p>
                </div>
              </motion.div>
            )}

            {/* PIN KEYPAD VIEW */}
            {activeTab === "pin" && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="w-full flex flex-col items-center"
              >
                {/* Input box */}
                <form onSubmit={handlePinSubmit} className="w-full max-w-xs mb-5 flex gap-2">
                  <input
                    type="password"
                    pattern="[0-9]*"
                    inputMode="numeric"
                    placeholder="Enter your PIN..."
                    value={pinValue}
                    onChange={(e) => setPinValue(e.target.value.replace(/\D/g, ""))}
                    disabled={isMatching}
                    className="flex-1 rounded-xl bg-surface-soft border border-hairline px-4 py-3 text-center text-lg font-bold tracking-widest text-white placeholder-zinc-700 focus:outline-none focus:border-primary transition-all shadow-inner font-mono"
                  />
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    type="submit"
                    disabled={isMatching || !pinValue.trim()}
                    className="bg-primary hover:bg-primary/95 text-white font-bold px-6 py-3 rounded-xl transition-all text-xs uppercase tracking-widest disabled:bg-surface-soft disabled:text-zinc-700 active:scale-[0.96] shadow-lg shadow-primary/10"
                  >
                    Enter
                  </motion.button>
                </form>

                {/* Grid Pad */}
                <div className="grid grid-cols-3 gap-2.5 max-w-xs w-full">
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((num) => (
                    <motion.button
                      whileTap={{ scale: 0.92 }}
                      transition={{ type: "spring", stiffness: 400, damping: 15 }}
                      key={num}
                      type="button"
                      onClick={() => handleKeypadPress(num.toString())}
                      disabled={isMatching}
                      className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-white font-bold py-4 rounded-2xl border border-hairline transition-all text-base select-none shadow-md"
                    >
                      {num}
                    </motion.button>
                  ))}
                  <motion.button
                    whileTap={{ scale: 0.92 }}
                    type="button"
                    onClick={handleKeypadClear}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-rose-500 font-bold py-4 rounded-2xl border border-hairline transition-all text-[11px] uppercase tracking-wider select-none shadow-md"
                  >
                    Clear
                  </motion.button>
                  <motion.button
                    whileTap={{ scale: 0.92 }}
                    type="button"
                    onClick={() => handleKeypadPress("0")}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-white font-bold py-4 rounded-2xl border border-hairline transition-all text-base select-none shadow-md"
                  >
                    0
                  </motion.button>
                  <motion.button
                    whileTap={{ scale: 0.92 }}
                    type="button"
                    onClick={handleKeypadBackspace}
                    disabled={isMatching}
                    className="bg-surface-soft hover:bg-surface-elevated active:scale-95 text-zinc-400 font-bold py-4 rounded-2xl border border-hairline transition-all flex items-center justify-center select-none shadow-md"
                  >
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3 12l6.414-6.414A2 2 0 0010.828 5H20a2 2 0 012 2v10a2 2 0 01-2 2h-9.172a2 2 0 01-1.414-.586L3 12z" />
                    </svg>
                  </motion.button>
                </div>
              </motion.div>
            )}
          </div>
        )}

        {/* ADMIN SETTINGS PANEL OVERLAY */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 30 }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute inset-0 bg-canvas z-40 flex flex-col p-6 overflow-y-auto"
            >
              <div className="max-w-2xl w-full mx-auto space-y-6 pb-12">
                <div className="flex justify-between items-center border-b border-hairline pb-4 mb-2">
                  <div>
                    <h2 className="text-base font-bold text-white uppercase tracking-wider">Admin Control Panel</h2>
                    <p className="text-[10px] text-zinc-500 uppercase tracking-widest mt-1">Configure kiosk preferences, pairing and profiles</p>
                  </div>
                  <button
                    onClick={() => setShowSettings(false)}
                    className="bg-surface-soft hover:bg-surface-elevated text-zinc-300 px-4 py-2 border border-hairline rounded-xl text-[10px] uppercase font-bold tracking-widest transition-all active:scale-[0.96]"
                  >
                    Done
                  </button>
                </div>

                {/* Server connection setup */}
                <div className="bg-surface-card rounded-2xl border border-hairline p-5 space-y-4 shadow-xl">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider">1. Kiosk Connection Settings</h3>
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      const target = e.currentTarget;
                      const urlVal = (target.elements.namedItem("settings_url") as HTMLInputElement).value;
                      const codeVal = (target.elements.namedItem("settings_code") as HTMLInputElement).value;

                      let formatted = urlVal.trim();
                      if (formatted && !/^https?:\/\//i.test(formatted)) {
                        formatted = `http://${formatted}`;
                      }
                      if (formatted.endsWith("/")) {
                        formatted = formatted.slice(0, -1);
                      }
                      localStorage.setItem("aegis_api_url", formatted);
                      setApiUrl(formatted);

                      if (codeVal.trim()) {
                        logMessage(`Attempting device pairing with code: ${codeVal.trim()}...`, "info");
                        try {
                          const pairRes = await fetch(`${formatted}/api/kiosk/pair`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ pairing_code: codeVal.trim() }),
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
                        fetchToken();
                      }
                    }}
                    className="space-y-4"
                  >
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-bold uppercase tracking-wider text-zinc-400 mb-1.5">Server API URL</label>
                        <input
                          name="settings_url"
                          defaultValue={apiUrl}
                          required
                          type="text"
                          className="w-full rounded-xl bg-surface-soft border border-hairline text-xs py-2.5 px-3.5 outline-none text-white focus:border-primary transition-all font-mono"
                          placeholder="e.g. http://192.168.254.105:8001"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-bold uppercase tracking-wider text-zinc-400 mb-1.5">Device Pairing Code (Optional)</label>
                        <input
                          name="settings_code"
                          type="text"
                          maxLength={8}
                          className="w-full rounded-xl bg-surface-soft border border-hairline text-xs py-2.5 px-3.5 outline-none text-white focus:border-primary transition-all font-mono uppercase"
                          placeholder="e.g. TZAX5Q8Z"
                        />
                      </div>
                    </div>
                    <button
                      type="submit"
                      className="bg-primary hover:bg-primary/90 text-white font-bold py-2.5 px-5 rounded-xl text-xs uppercase tracking-widest transition-all active:scale-[0.96] shadow-lg shadow-primary/20"
                    >
                      Save & Reconnect
                    </button>
                  </form>
                </div>

                {/* Camera configuration */}
                <div className="bg-surface-card rounded-2xl border border-hairline p-5 space-y-4 shadow-xl">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider">2. Camera & Gating Settings</h3>
                  <div className="flex flex-col md:flex-row gap-4">
                    <button
                      onClick={() => setFacingMode(prev => prev === "user" ? "environment" : "user")}
                      className="flex-1 bg-surface-soft hover:bg-surface-elevated text-white border border-hairline py-3 px-4 rounded-xl text-xs font-bold uppercase tracking-wider transition-all active:scale-[0.96] text-center"
                    >
                      Switch Camera: {facingMode === "user" ? "Front (Selfie)" : "Back (Room)"}
                    </button>
                    <button
                      onClick={() => setRelaxedGating(!relaxedGating)}
                      className={`flex-1 border py-3 px-4 rounded-xl text-xs font-bold uppercase tracking-wider transition-all active:scale-[0.96] text-center ${
                        relaxedGating
                          ? "bg-amber-950/20 border-amber-800/40 text-amber-400"
                          : "bg-surface-soft border-hairline text-zinc-400"
                      }`}
                    >
                      Relax Scan Criteria: {relaxedGating ? "ENABLED" : "DISABLED"}
                    </button>
                  </div>
                </div>

                {/* Face Registration (Enrollment) */}
                <div className="bg-surface-card rounded-2xl border border-hairline p-5 space-y-5 shadow-xl">
                  <div className="flex justify-between items-center border-b border-hairline pb-3">
                    <h3 className="text-xs font-bold text-white uppercase tracking-wider">3. Biometrics Enrollment</h3>
                    <button
                      onClick={() => {
                        const mode = !showEnroll;
                        setShowEnroll(mode);
                        setActiveScan(!mode);
                      }}
                      className={`px-3 py-1 rounded-full text-[9px] font-bold uppercase tracking-wider border ${
                        showEnroll
                          ? "bg-emerald-950/30 border-emerald-800/40 text-emerald-400"
                          : "bg-surface-soft border-hairline text-zinc-400"
                      }`}
                    >
                      {showEnroll ? "Registration Active" : "Activate Registration"}
                    </button>
                  </div>

                  {showEnroll ? (
                    <div className="space-y-4 animate-scale-up">
                      <div className="relative aspect-[4/3] rounded-2xl overflow-hidden border border-hairline bg-black">
                        <video
                          ref={videoRef}
                          autoPlay
                          playsInline
                          muted
                          className="h-full w-full object-cover transform scale-x-[-1]"
                        />
                        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/40">
                          <div className="h-56 w-44 rounded-[100px] border-2 border-dashed border-primary animate-pulse" />
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          placeholder="Employee Full Name..."
                          value={enrollName}
                          onChange={(e) => setEnrollName(e.target.value)}
                          disabled={isEnrolling}
                          className="flex-1 rounded-xl bg-surface-soft border border-hairline px-4 py-2.5 text-xs text-white placeholder-zinc-600 focus:outline-none focus:border-primary transition-all font-semibold"
                        />
                        <button
                          onClick={enrollFace}
                          disabled={isEnrolling || !enrollName.trim()}
                          className="bg-emerald-500 hover:bg-emerald-600 text-white font-bold px-5 py-2.5 rounded-xl text-xs uppercase tracking-widest transition-all disabled:bg-surface-soft disabled:text-zinc-600 active:scale-[0.96]"
                        >
                          {isEnrolling ? "Saving..." : "Enroll Face"}
                        </button>
                      </div>
                      {enrollSuccess && <p className="text-xs text-emerald-400 font-semibold">{enrollSuccess}</p>}
                      {enrollError && <p className="text-xs text-rose-400 font-semibold">{enrollError}</p>}
                    </div>
                  ) : (
                    <p className="text-xs text-zinc-500 italic">Toggle "Activate Registration" to enroll employees' faces via this camera.</p>
                  )}

                  {/* Profile manager */}
                  <div className="border-t border-hairline pt-4 space-y-3">
                    <div className="flex justify-between items-center">
                      <h4 className="text-[10px] font-bold text-white uppercase tracking-wider">Registered Profiles ({people.length})</h4>
                      {people.length > 0 && (
                        <button
                          onClick={deleteAllPeople}
                          className="text-[9px] text-rose-500 hover:text-rose-400 uppercase font-bold tracking-wider"
                        >
                          Delete All
                        </button>
                      )}
                    </div>
                    <div className="max-h-48 overflow-y-auto space-y-2 scrollbar-thin">
                      {people.length === 0 ? (
                        <p className="text-[9px] text-zinc-600 uppercase tracking-widest text-center py-2">No registered profiles.</p>
                      ) : (
                        people.map(p => (
                          <div key={p.id} className="flex justify-between items-center bg-surface-soft border border-hairline rounded-xl px-3.5 py-2">
                            <span className="text-xs font-semibold text-white">{p.display_name}</span>
                            <button
                              onClick={() => deletePerson(p.id, p.display_name)}
                              className="text-[9px] text-rose-500 hover:text-rose-400 uppercase font-bold"
                            >
                              Delete
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                {/* Dev Logs */}
                <div className="bg-surface-card rounded-2xl border border-hairline p-5 space-y-4 shadow-xl">
                  <div className="flex justify-between items-center border-b border-hairline pb-2">
                    <h3 className="text-xs font-bold text-white uppercase tracking-wider">4. Live Logs Console</h3>
                    <div className="flex gap-2">
                      <button
                        onClick={resetLockout}
                        className="text-[9px] bg-surface-soft border border-hairline hover:border-zinc-400 text-zinc-300 px-3 py-1 rounded-xl uppercase font-bold"
                      >
                        Reset Lockout
                      </button>
                      <button
                        onClick={() => setLogs([])}
                        className="text-[9px] bg-surface-soft border border-hairline hover:border-zinc-400 text-zinc-300 px-3 py-1 rounded-xl uppercase font-bold"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <div className="h-48 overflow-y-auto font-mono text-[9px] text-zinc-500 bg-surface-soft border border-hairline rounded-xl p-3 scrollbar-thin select-text">
                    {logs.length === 0 ? (
                      <p className="italic text-center py-4">Console empty.</p>
                    ) : (
                      logs.map((log, idx) => (
                        <div
                          key={idx}
                          className={
                            log.includes("ERROR:") || log.includes("failed") || log.includes("401")
                              ? "text-rose-400"
                              : log.includes("success") || log.includes("paired")
                              ? "text-emerald-400"
                              : "text-zinc-400"
                          }
                        >
                          {log}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      {/* Success / Error / Info Notifications overlays */}
      <AnimatePresence>
        {scanResult && scanResult.person && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/95 backdrop-blur-md z-50 flex items-center justify-center p-6"
          >
            <motion.div
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 20 }}
              transition={{ type: "spring", damping: 20, stiffness: 200 }}
              className="flex flex-col items-center text-center p-8 max-w-sm w-full rounded-3xl bg-surface-card border border-emerald-500/20 shadow-2xl"
            >
              <div className="h-20 w-20 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-5 animate-pulse">
                <svg className="h-10 w-10 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-xl font-bold tracking-wide text-white mb-2 uppercase">Punch Success</h3>
              <p className="text-white text-lg font-bold mb-1">{scanResult.person.display_name}</p>
              <p className="text-zinc-500 text-[10px] font-bold uppercase tracking-wider mb-4">
                {scanResult.direction === "in" ? "CHECK-IN" : "CHECK-OUT"} • {new Date(scanResult.occurred_at).toLocaleTimeString()}
              </p>
              <span className="text-[10px] text-zinc-300 bg-surface-soft border border-hairline rounded-full px-4 py-2 uppercase font-bold tracking-wider">
                Attendance Logged
              </span>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {scanError && (
          <motion.div
            initial={{ opacity: 0, y: 30, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 30, scale: 0.9 }}
            className="fixed bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-3.5 bg-rose-950/95 border border-rose-800/40 backdrop-blur-md rounded-full px-5 py-3 shadow-2xl z-50"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-pulse shadow-[0_0_6px_rgba(244,63,94,0.6)]" />
            <span className="text-rose-200 text-xs font-bold uppercase tracking-wider">{scanError}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {scanInfo && (
          <motion.div
            initial={{ opacity: 0, y: 30, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 30, scale: 0.9 }}
            className="fixed bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-3.5 bg-zinc-900/95 border border-hairline backdrop-blur-md rounded-full px-5 py-3 shadow-2xl z-50"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse shadow-[0_0_6px_rgba(255,255,255,0.6)]" />
            <span className="text-white text-xs font-bold uppercase tracking-wider">{scanInfo}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Footer */}
      <footer className="py-6 text-center select-none text-[10px] text-zinc-600 uppercase tracking-widest font-semibold shrink-0">
        &copy; {new Date().getFullYear()} Aegis Biometrics. All rights reserved.
      </footer>
    </main>
  );
}
