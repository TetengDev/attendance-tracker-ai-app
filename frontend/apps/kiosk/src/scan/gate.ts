import type { Detection } from "@mediapipe/tasks-vision";
import type { GateMetrics } from "@attendance/protocol";

export interface GateSettings {
  min_bbox_area_pct: number;
  min_interocular_px: number;
  max_center_offset_pct: number;
  min_sharpness: number;
  luma_min: number;
  luma_max: number;
}

export interface GateResult {
  passed: boolean;
  metrics: GateMetrics;
  reason?: string;
}

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Computes IoU (Intersection over Union) of two bounding boxes.
 */
export function computeIoU(boxA: BBox, boxB: BBox): number {
  const xA = Math.max(boxA.x, boxB.x);
  const yA = Math.max(boxA.y, boxB.y);
  const xB = Math.min(boxA.x + boxA.w, boxB.x + boxB.w);
  const yB = Math.min(boxA.y + boxA.h, boxB.y + boxB.h);

  const interArea = Math.max(0, xB - xA) * Math.max(0, yB - yA);
  const boxAArea = boxA.w * boxA.h;
  const boxBArea = boxB.w * boxB.h;

  const unionArea = boxAArea + boxBArea - interArea;
  if (unionArea === 0) return 0;

  return interArea / unionArea;
}

/**
 * Computes the variance of the Laplacian of a canvas region (sharpness metric).
 * Takes pre-extracted ImageData to avoid duplicate GPU-to-CPU copy overhead.
 */
export function computeLaplacianVariance(imgData: ImageData): number {
  const w = imgData.width;
  const h = imgData.height;
  if (w <= 2 || h <= 2) return 0;

  const data = imgData.data;

  // Grayscale conversion
  const gray = new Float32Array(w * h);
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i] ?? 0;
    const g = data[i + 1] ?? 0;
    const b = data[i + 2] ?? 0;
    gray[i / 4] = 0.299 * r + 0.587 * g + 0.114 * b;
  }

  // 4-neighborhood Laplacian convolution
  const lap = new Float32Array((w - 2) * (h - 2));
  let sum = 0;
  let count = 0;

  for (let cy = 1; cy < h - 1; cy++) {
    for (let cx = 1; cx < w - 1; cx++) {
      const idx = cy * w + cx;
      const top = gray[idx - w] ?? 0;
      const left = gray[idx - 1] ?? 0;
      const center = gray[idx] ?? 0;
      const right = gray[idx + 1] ?? 0;
      const bottom = gray[idx + w] ?? 0;

      const val = top + left - 4 * center + right + bottom;

      lap[count] = val;
      sum += val;
      count++;
    }
  }

  if (count === 0) return 0;
  const mean = sum / count;

  let varSum = 0;
  for (let i = 0; i < count; i++) {
    const diff = (lap[i] ?? 0) - mean;
    varSum += diff * diff;
  }

  return varSum / count;
}

/**
 * Computes the mean luma (brightness) of a canvas region.
 * Takes pre-extracted ImageData to avoid duplicate GPU-to-CPU copy overhead.
 */
export function computeMeanLuma(imgData: ImageData): number {
  const w = imgData.width;
  const h = imgData.height;
  if (w <= 0 || h <= 0) return 0;

  const data = imgData.data;
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i] ?? 0;
    const g = data[i + 1] ?? 0;
    const b = data[i + 2] ?? 0;
    sum += 0.299 * r + 0.587 * g + 0.114 * b;
  }
  return sum / (w * h);
}

/**
 * Runs individual frame gating checks on a 320x240 offscreen canvas.
 */
export function checkFrameGates(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  settings: GateSettings
): GateResult {
  const metrics: GateMetrics = {
    bbox_area_pct: 0,
    interocular_px: 0,
    center_offset_pct: 0,
    sharpness: 0,
    luma: 0,
  };

  if (detections.length === 0) {
    return { passed: false, metrics, reason: "no_face" };
  }
  if (detections.length > 1) {
    return { passed: false, metrics, reason: "multiple_faces" };
  }

  const det = detections[0];
  if (!det) {
    return { passed: false, metrics, reason: "no_face" };
  }

  const bbox = det.boundingBox;
  if (!bbox) {
    return { passed: false, metrics, reason: "no_bbox" };
  }

  // 1. BBox Area Pct (canvas is 320x240 = 76800 px)
  const area = bbox.width * bbox.height;
  const areaPct = (area / 76800) * 100;
  metrics.bbox_area_pct = parseFloat(areaPct.toFixed(2));

  if (areaPct < settings.min_bbox_area_pct) {
    return {
      passed: false,
      metrics,
      reason: `bbox_area_too_small (${metrics.bbox_area_pct}% < ${settings.min_bbox_area_pct}%)`,
    };
  }

  // 2. Interocular Distance (eye keypoints 0 and 1)
  const keypoints = det.keypoints;
  if (!keypoints) {
    return { passed: false, metrics, reason: "missing_eye_keypoints" };
  }

  const kp0 = keypoints[0];
  const kp1 = keypoints[1];
  if (!kp0 || !kp1) {
    return { passed: false, metrics, reason: "missing_eye_keypoints" };
  }

  const x0 = kp0.x * 320;
  const y0 = kp0.y * 240;
  const x1 = kp1.x * 320;
  const y1 = kp1.y * 240;

  const iod = Math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2);
  metrics.interocular_px = parseFloat(iod.toFixed(2));

  if (iod < settings.min_interocular_px) {
    return {
      passed: false,
      metrics,
      reason: `interocular_too_small (${metrics.interocular_px}px < ${settings.min_interocular_px}px)`,
    };
  }

  // 3. Centered within X%
  // Center of bbox:
  const cx = bbox.originX + bbox.width / 2;
  const cy = bbox.originY + bbox.height / 2;
  const dx = Math.abs(cx - 160) / 320 * 100;
  const dy = Math.abs(cy - 120) / 240 * 100;
  metrics.center_offset_pct = parseFloat(Math.max(dx, dy).toFixed(2));

  if (metrics.center_offset_pct > settings.max_center_offset_pct) {
    return {
      passed: false,
      metrics,
      reason: `not_centered (${metrics.center_offset_pct}% > ${settings.max_center_offset_pct}%)`,
    };
  }

  // Clip bounding box for pixel calculations
  const rx = Math.max(0, Math.floor(bbox.originX));
  const ry = Math.max(0, Math.floor(bbox.originY));
  const rw = Math.min(320 - rx, Math.floor(bbox.width));
  const rh = Math.min(240 - ry, Math.floor(bbox.height));

  if (rw <= 0 || rh <= 0) {
    return { passed: false, metrics, reason: "invalid_bbox_dimensions" };
  }

  // Single GPU-to-CPU canvas readback copy for both Laplacian & Luma
  const imgData = ctx.getImageData(rx, ry, rw, rh);

  // 4. Sharpness (Variance of Laplacian)
  const sharpness = computeLaplacianVariance(imgData);
  metrics.sharpness = parseFloat(sharpness.toFixed(2));

  if (sharpness < settings.min_sharpness) {
    return {
      passed: false,
      metrics,
      reason: `blurry (${metrics.sharpness} < ${settings.min_sharpness})`,
    };
  }

  // 5. Mean Luma (Brightness)
  const luma = computeMeanLuma(imgData);
  metrics.luma = parseFloat(luma.toFixed(2));

  if (luma < settings.luma_min || luma > settings.luma_max) {
    return {
      passed: false,
      metrics,
      reason: `invalid_luma (${metrics.luma} outside [${settings.luma_min}, ${settings.luma_max}])`,
    };
  }

  return { passed: true, metrics };
}
