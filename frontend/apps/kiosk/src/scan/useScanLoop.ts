import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision";
import type { FrameBurst, FrameItem, GateMetrics } from "@attendance/protocol";
import { checkFrameGates, computeIoU, type BBox, type GateSettings } from "./gate";

export interface UseScanLoopOptions {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  facingMode?: "user" | "environment";
  scanMode?: "continuous" | "tap_to_scan";
  isScanActive?: boolean;
  isAppBackgrounded?: boolean;
  isSessionIdle?: boolean;
  settings?: Partial<
    GateSettings & {
      stability_iou: number;
      stability_frames: number;
      stability_ms: number;
      burst_count: number;
      burst_interval_ms: number;
    }
  >;
  onDetected?: () => void;
  onGatingPassed?: (metrics: GateMetrics) => void;
  onGatingFailed?: (reason: string, metrics: GateMetrics) => void;
  onBurstCaptured?: (burst: FrameBurst) => void;
}

export interface UseScanLoopResult {
  isLoadingModel: boolean;
  modelError: string | null;
  cameraError: string | null;
  isScanRunning: boolean;
  metrics: GateMetrics | null;
  reason: string | null;
  resetLockout: () => void;
  detectedBbox: { x: number; y: number; w: number; h: number } | null;
}

interface StabilityFrame {
  timestamp: number;
  bbox: BBox;
}

// Module-level cached Singleton for MediaPipe FaceDetector to prevent repeated loads
let cachedDetector: FaceDetector | null = null;
let loadingPromise: Promise<FaceDetector> | null = null;

async function getFaceDetector(): Promise<FaceDetector> {
  if (cachedDetector) return cachedDetector;
  if (loadingPromise) return loadingPromise;

  loadingPromise = (async () => {
    try {
      const vision = await FilesetResolver.forVisionTasks("/wasm");
      cachedDetector = await FaceDetector.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: "/face_detector.tflite",
          delegate: "GPU",
        },
        runningMode: "IMAGE",
      });
      return cachedDetector;
    } catch (err) {
      // Clear promise on failure to allow retry
      loadingPromise = null;
      throw err;
    }
  })();

  return loadingPromise;
}

function createMockCameraStream(): MediaStream {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 480;
  const ctx = canvas.getContext("2d");
  
  let frame = 0;
  const intervalId = setInterval(() => {
    if (!ctx) return;
    frame++;
    
    // Draw background
    ctx.fillStyle = "#09090b";
    ctx.fillRect(0, 0, 640, 480);
    
    // Draw grid lines
    ctx.strokeStyle = "#18181b";
    ctx.lineWidth = 1;
    for (let x = 0; x < 640; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 480);
      ctx.stroke();
    }
    for (let y = 0; y < 480; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(640, y);
      ctx.stroke();
    }

    // Draw scanning laser
    const laserY = (Math.sin(frame * 0.05) + 1) * 240;
    ctx.strokeStyle = "#6366f1";
    ctx.lineWidth = 3;
    ctx.shadowBlur = 15;
    ctx.shadowColor = "#6366f1";
    ctx.beginPath();
    ctx.moveTo(40, laserY);
    ctx.lineTo(600, laserY);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Draw simulated face outline
    ctx.strokeStyle = "rgba(99, 102, 241, 0.4)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(320, 240, 100, 0, Math.PI * 2);
    ctx.stroke();

    // Draw eyes and mouth
    ctx.beginPath();
    ctx.arc(280, 210, 8, 0, Math.PI * 2);
    ctx.arc(360, 210, 8, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(99, 102, 241, 0.4)";
    ctx.fill();

    ctx.beginPath();
    ctx.arc(320, 270, 30, 0, Math.PI);
    ctx.stroke();

    // Draw status text
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 16px monospace";
    ctx.textAlign = "center";
    ctx.fillText("AEGIS CAMERA SIMULATOR (ACTIVE)", 320, 50);
    
    ctx.fillStyle = "#a1a1aa";
    ctx.font = "12px monospace";
    ctx.fillText("Simulating front-facing camera input", 320, 80);
  }, 33);

  const stream = (canvas as any).captureStream 
    ? (canvas as any).captureStream(30) 
    : (canvas as any).webkitCaptureStream 
      ? (canvas as any).webkitCaptureStream(30) 
      : null;
  if (stream) {
    const originalStop = stream.getVideoTracks()[0].stop;
    stream.getVideoTracks()[0].stop = function() {
      clearInterval(intervalId);
      originalStop.apply(this);
    };
    return stream;
  }
  
  return new MediaStream();
}

export function useScanLoop({
  videoRef,
  facingMode = "user",
  scanMode = "tap_to_scan",
  isScanActive = false,
  isAppBackgrounded = false,
  isSessionIdle = false,
  settings = {},
  onDetected,
  onGatingPassed,
  onGatingFailed,
  onBurstCaptured,
}: UseScanLoopOptions): UseScanLoopResult {
  const [isLoadingModel, setIsLoadingModel] = useState(true);
  const [modelError, setModelError] = useState<string | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [isScanRunning, setIsScanRunning] = useState(false);
  const [metrics, setMetrics] = useState<GateMetrics | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [detectedBbox, setDetectedBbox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  // Memoize resolved gate settings to prevent loop recreation on every render/frame
  const resolvedSettings = useMemo(
    () => ({
      min_bbox_area_pct: settings.min_bbox_area_pct ?? 8.0,
      min_interocular_px: settings.min_interocular_px ?? 90,
      max_center_offset_pct: settings.max_center_offset_pct ?? 20.0,
      min_sharpness: settings.min_sharpness ?? 60.0,
      luma_min: settings.luma_min ?? 40,
      luma_max: settings.luma_max ?? 220,
      stability_iou: settings.stability_iou ?? 0.90,
      stability_frames: settings.stability_frames ?? 3,
      stability_ms: settings.stability_ms ?? 120,
      burst_count: settings.burst_count ?? 2,
      burst_interval_ms: settings.burst_interval_ms ?? 150,
    }),
    [
      settings.min_bbox_area_pct,
      settings.min_interocular_px,
      settings.max_center_offset_pct,
      settings.min_sharpness,
      settings.luma_min,
      settings.luma_max,
      settings.stability_iou,
      settings.stability_frames,
      settings.stability_ms,
      settings.burst_count,
      settings.burst_interval_ms,
    ]
  );

  const activeStreamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<FaceDetector | null>(null);
  const requestRef = useRef<number | null>(null);

  // Offscreen canvases
  const canvas320Ref = useRef<HTMLCanvasElement | null>(null);
  const canvas480Ref = useRef<HTMLCanvasElement | null>(null);

  // Gating & Stability state
  const stabilityQueueRef = useRef<StabilityFrame[]>([]);
  const isCapturingBurstRef = useRef(false);
  const lastBurstTimeRef = useRef(0);

  // Success Lockout state (locks loop after match success until face leaves frame)
  const isLockedOutRef = useRef(false);
  const matchedBboxRef = useRef<BBox | null>(null);

  const resetLockout = useCallback(() => {
    isLockedOutRef.current = false;
    matchedBboxRef.current = null;
  }, []);

  // Initialize offscreen canvases
  useEffect(() => {
    const canvas320 = document.createElement("canvas");
    canvas320.width = 320;
    canvas320.height = 240;
    canvas320Ref.current = canvas320;

    const canvas480 = document.createElement("canvas");
    canvas480.width = 480;
    canvas480.height = 480;
    canvas480Ref.current = canvas480;
  }, []);

  // Load Face Detector model
  useEffect(() => {
    setIsLoadingModel(true);
    getFaceDetector()
      .then((det) => {
        detectorRef.current = det;
        setIsLoadingModel(false);
      })
      .catch((err) => {
        console.error("Failed to load FaceDetector:", err);
        setModelError("Failed to load face detection models.");
        setIsLoadingModel(false);
      });
  }, []);

  // Stop camera stream helper
  const stopCamera = useCallback(() => {
    stabilityQueueRef.current = []; // Clear queue on stream stop
    setDetectedBbox(null);
    if (activeStreamRef.current) {
      activeStreamRef.current.getTracks().forEach((track) => track.stop());
      activeStreamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsScanRunning(false);
  }, [videoRef]);

  // Start camera stream helper
  const startCamera = useCallback(async () => {
    stopCamera();
    setCameraError(null);
    stabilityQueueRef.current = []; // Clear queue on stream start

    const constraints: MediaStreamConstraints = {
      video: {
        facingMode: facingMode,
      },
      audio: false,
    };

    try {
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      activeStreamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadedmetadata = () => {
          videoRef.current?.play().catch(console.error);
        };
      }
      setIsScanRunning(true);
    } catch (err: any) {
      console.warn("Failed to acquire real camera stream. Falling back to simulator stream:", err);
      try {
        const mockStream = createMockCameraStream();
        activeStreamRef.current = mockStream;
        if (videoRef.current) {
          videoRef.current.srcObject = mockStream;
          videoRef.current.onloadedmetadata = () => {
            videoRef.current?.play().catch(console.error);
          };
        }
        setIsScanRunning(true);
      } catch (mockErr) {
        console.error("Failed to acquire simulated camera stream:", mockErr);
        setCameraError("Camera access denied or unavailable.");
      }
    }
  }, [facingMode, stopCamera, videoRef]);

  // Handle stream lifecycle based on backgrounding, idle, scan mode
  useEffect(() => {
    const shouldRun =
      !isAppBackgrounded &&
      !isSessionIdle &&
      (scanMode === "continuous" || isScanActive);

    if (shouldRun) {
      startCamera();
    } else {
      stopCamera();
    }

    return () => {
      stopCamera();
    };
  }, [
    isAppBackgrounded,
    isSessionIdle,
    scanMode,
    isScanActive,
    startCamera,
    stopCamera,
  ]);

  // Capture Frame Burst sequence (pre-declared to avoid circular reference in loop)
  const captureBurst = useCallback(
    async (triggerBbox: BBox, gateMetrics: GateMetrics) => {
      const video = videoRef.current;
      const detector = detectorRef.current;
      const canvas320 = canvas320Ref.current;
      const canvas480 = canvas480Ref.current;

      if (!video || !detector || !canvas320 || !canvas480) {
        isCapturingBurstRef.current = false;
        return;
      }

      const burstId = crypto.randomUUID();
      const burstFrames: FrameItem[] = [];

      // Helper to capture a single burst frame
      const captureFrame = async (): Promise<FrameItem | null> => {
        const ctx320 = canvas320.getContext("2d");
        if (!ctx320) return null;
        ctx320.drawImage(video, 0, 0, 320, 240);

        // Perform a face detection check on the current frame
        const detResult = detector.detect(canvas320);
        const det = detResult.detections[0];
        if (
          detResult.detections.length !== 1 ||
          !det ||
          !det.boundingBox
        ) {
          return null; // Ignore if face count is wrong or missing bbox
        }

        const bbox = det.boundingBox;

        // Extract raw video dimensions for accurate letterboxing
        const srcW = video.videoWidth;
        const srcH = video.videoHeight;

        // Scale coordinates from 320x240 detector space to original video space
        const scaleX = srcW / 320;
        const scaleY = srcH / 240;

        const vidBbox = {
          x: bbox.originX * scaleX,
          y: bbox.originY * scaleY,
          w: bbox.width * scaleX,
          h: bbox.height * scaleY,
        };

        // Math for a square 4.0x expanded crop box
        const cx = vidBbox.x + vidBbox.w / 2;
        const cy = vidBbox.y + vidBbox.h / 2;
        const size = Math.max(vidBbox.w * 4.0, vidBbox.h * 4.0);

        const cropX = cx - size / 2;
        const cropY = cy - size / 2;

        // Draw onto 480x480 offscreen canvas with letterbox padding
        const ctx480 = canvas480.getContext("2d");
        if (!ctx480) return null;
        ctx480.fillStyle = "black";
        ctx480.fillRect(0, 0, 480, 480);

        const sX = Math.max(0, cropX);
        const sY = Math.max(0, cropY);
        const sW = Math.min(srcW - sX, cropX + size - sX);
        const sH = Math.min(srcH - sY, cropY + size - sY);

        if (sW > 0 && sH > 0) {
          const dX = ((sX - cropX) / size) * 480;
          const dY = ((sY - cropY) / size) * 480;
          const dW = (sW / size) * 480;
          const dH = (sH / size) * 480;
          ctx480.drawImage(video, sX, sY, sW, sH, dX, dY, dW, dH);
        }

        // Coordinates of original face bounding box relative to 480x480 cropped space
        const relX = ((vidBbox.x - cropX) / size) * 480;
        const relY = ((vidBbox.y - cropY) / size) * 480;
        const relW = (vidBbox.w / size) * 480;
        const relH = (vidBbox.h / size) * 480;

        const finalBbox: [number, number, number, number] = [
          Math.round(relX),
          Math.round(relY),
          Math.round(relX + relW),
          Math.round(relY + relH),
        ];

        // Export as base64 JPEG
        const dataUrl = canvas480.toDataURL("image/jpeg", 0.85);
        const jpeg_b64 = dataUrl.split(",")[1] ?? "";

        return {
          jpeg_b64,
          bbox: finalBbox,
          monotonic_offset_ms: performance.now(),
        };
      };

      // Capture first frame immediately
      const firstFrame = await captureFrame();
      if (firstFrame) {
        burstFrames.push(firstFrame);
      }

      // Capture subsequent frames at configured intervals
      const burstCount = resolvedSettings.burst_count;
      const intervalMs = resolvedSettings.burst_interval_ms;

      for (let i = 1; i < burstCount; i++) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        const nextFrame = await captureFrame();
        if (nextFrame) {
          burstFrames.push(nextFrame);
        }
      }

      // Submit burst if we got at least one valid frame
      if (burstFrames.length > 0) {
        // Lock loop with trigger bbox to prevent spamming
        isLockedOutRef.current = true;
        matchedBboxRef.current = triggerBbox;
        lastBurstTimeRef.current = performance.now();

        const burstPayload: FrameBurst = {
          type: "frame_burst",
          idempotency_key: burstId,
          burst_seq: 1, // first sequence
          frames: burstFrames,
          gate_metrics: gateMetrics,
        };

        if (onBurstCaptured) {
          onBurstCaptured(burstPayload);
        }
      }

      isCapturingBurstRef.current = false;
    },
    [videoRef, resolvedSettings, onBurstCaptured]
  );

  // Main scan loop tick
  useEffect(() => {
    const loop = async () => {
      // Early return if scanning is disabled/not running
      if (!isScanRunning) return;

      const video = videoRef.current;
      const detector = detectorRef.current;
      const canvas320 = canvas320Ref.current;
      const canvas480 = canvas480Ref.current;

      if (
        !video ||
        !detector ||
        !canvas320 ||
        !canvas480 ||
        video.paused ||
        video.ended ||
        isCapturingBurstRef.current
      ) {
        requestRef.current = requestAnimationFrame(loop);
        return;
      }

      // Draw standard 320x240 frame to offscreen canvas
      const ctx320 = canvas320.getContext("2d");
      if (!ctx320) {
        requestRef.current = requestAnimationFrame(loop);
        return;
      }
      ctx320.drawImage(video, 0, 0, 320, 240);

      // Detect faces
      const detectorResult = detector.detect(canvas320);
      const detections = detectorResult.detections;

      // Update detected BBox state
      if (detections.length === 1 && detections[0]?.boundingBox) {
        const bbox = detections[0].boundingBox;
        setDetectedBbox({
          x: (bbox.originX / 320) * 100,
          y: (bbox.originY / 240) * 100,
          w: (bbox.width / 320) * 100,
          h: (bbox.height / 240) * 100,
        });
      } else {
        setDetectedBbox(null);
      }

      // Handle Lockout state: if locked out, check if face has left the frame
      if (isLockedOutRef.current) {
        const firstDet = detections[0];
        if (detections.length === 0) {
          // Clear lockout if face completely leaves
          isLockedOutRef.current = false;
          matchedBboxRef.current = null;
        } else if (detections.length === 1 && matchedBboxRef.current && firstDet) {
          const currentBbox = firstDet.boundingBox;
          if (currentBbox) {
            const currentBox: BBox = {
              x: currentBbox.originX,
              y: currentBbox.originY,
              w: currentBbox.width,
              h: currentBbox.height,
            };
            const iou = computeIoU(currentBox, matchedBboxRef.current);
            // If the face has moved enough (IoU < 0.5), we treat it as a new person/face
            if (iou < 0.5) {
              isLockedOutRef.current = false;
              matchedBboxRef.current = null;
            }
          }
        }
        // Skip gating while locked out
        requestRef.current = requestAnimationFrame(loop);
        return;
      }

      // Run individual frame gates
      const gateResult = checkFrameGates(ctx320, detections, resolvedSettings);
      setMetrics(gateResult.metrics);
      setReason(gateResult.reason || null);

      if (!gateResult.passed) {
        // Clear stability queue on gating failure (stability requires consecutive frames)
        stabilityQueueRef.current = [];
        if (gateResult.reason && onGatingFailed) {
          onGatingFailed(gateResult.reason, gateResult.metrics);
        }
      } else {
        if (onGatingPassed) {
          onGatingPassed(gateResult.metrics);
        }

        const det = detections[0];
        if (!det) {
          requestRef.current = requestAnimationFrame(loop);
          return;
        }

        const bbox = det.boundingBox;
        if (!bbox) {
          requestRef.current = requestAnimationFrame(loop);
          return;
        }

        const currentBox: BBox = {
          x: bbox.originX,
          y: bbox.originY,
          w: bbox.width,
          h: bbox.height,
        };

        const now = performance.now();
        const queue = stabilityQueueRef.current;

        // Verify if the current box is stable compared to the last tracked frame
        if (queue.length > 0) {
          const lastFrame = queue[queue.length - 1];
          if (lastFrame) {
            const iou = computeIoU(currentBox, lastFrame.bbox);
            if (iou < resolvedSettings.stability_iou) {
              // Face moved/drifted -> reset stability queue
              queue.length = 0;
            }
          }
        }

        // Push current passing frame to stability queue
        queue.push({ timestamp: now, bbox: currentBox });

        // Trim frames from the front that are older than stability_ms,
        // but keep at least stability_frames in the queue to maintain tracking history
        while (queue.length > resolvedSettings.stability_frames) {
          const nextFrame = queue[1];
          if (nextFrame && now - nextFrame.timestamp >= resolvedSettings.stability_ms) {
            queue.shift();
          } else {
            break;
          }
        }

        // Verify stability gate requirements
        let stabilityPassed = false;
        const q0 = queue[0];
        const qLast = queue[queue.length - 1];

        if (queue.length >= resolvedSettings.stability_frames && q0 && qLast) {
          const elapsed = qLast.timestamp - q0.timestamp;
          const timeOk = elapsed >= resolvedSettings.stability_ms;

          let iouOk = true;
          for (let i = 0; i < queue.length - 1; i++) {
            const qCur = queue[i];
            const qNext = queue[i + 1];
            if (qCur && qNext) {
              const iou = computeIoU(qCur.bbox, qNext.bbox);
              if (iou < resolvedSettings.stability_iou) {
                iouOk = false;
                break;
              }
            }
          }

          stabilityPassed = timeOk && iouOk;
        }

        const throttleOk = now - lastBurstTimeRef.current >= 400;

        if (stabilityPassed && throttleOk) {
          // Trigger frame burst capture!
          isCapturingBurstRef.current = true;
          stabilityQueueRef.current = []; // Clear queue

          if (onDetected) {
            onDetected();
          }

          captureBurst(currentBox, gateResult.metrics);
          requestRef.current = requestAnimationFrame(loop);
          return;
        }
      }

      requestRef.current = requestAnimationFrame(loop);
    };

    if (isScanRunning) {
      requestRef.current = requestAnimationFrame(loop);
    }

    return () => {
      if (requestRef.current !== null) {
        cancelAnimationFrame(requestRef.current);
        requestRef.current = null;
      }
    };
  }, [
    isScanRunning,
    resolvedSettings,
    onDetected,
    onGatingPassed,
    onGatingFailed,
    captureBurst,
    videoRef,
  ]);

  return {
    isLoadingModel,
    modelError,
    cameraError,
    isScanRunning,
    metrics,
    reason,
    resetLockout,
    detectedBbox,
  };
}
