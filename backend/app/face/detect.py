import cv2
import numpy as np
import onnxruntime  # type: ignore[import-untyped]

from backend.app.face.protocol import Detection


def distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, i % 2] + distance[:, i]
        py = points[:, i % 2 + 1] + distance[:, i + 1]
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


def nms(bboxes: np.ndarray, scores: np.ndarray, thresh: float = 0.4) -> list[int]:
    x1 = bboxes[:, 0]
    y1 = bboxes[:, 1]
    x2 = bboxes[:, 2]
    y2 = bboxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    areas = np.clip(areas, 0, None)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)

        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]
    return keep


class SCRFDDetector:
    def __init__(self, model_path: str, det_size: int = 384) -> None:
        self.session = onnxruntime.InferenceSession(model_path)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.det_size = det_size

        # Statically cache anchors for det_size x det_size input size
        self.anchors = {}
        for stride in [8, 16, 32]:
            h = det_size // stride
            w = det_size // stride
            anchor_centers = np.transpose(np.mgrid[:h, :w][::-1], (1, 2, 0)).astype(np.float32)
            anchor_centers = (anchor_centers * stride).reshape((-1, 2))
            # det_10g has 2 anchors per grid location
            anchor_centers = np.stack((anchor_centers, anchor_centers), axis=1).reshape((-1, 2))
            self.anchors[stride] = anchor_centers

    def detect(self, bgr: np.ndarray, det_thresh: float = 0.60) -> list[Detection]:
        # Preprocess: letterbox resize to det_size x det_size
        input_size = (self.det_size, self.det_size)
        im_ratio = float(bgr.shape[0]) / bgr.shape[1]
        model_ratio = 1.0
        if im_ratio > model_ratio:
            new_height = input_size[1]
            new_width = int(new_height / im_ratio)
        else:
            new_width = input_size[0]
            new_height = int(new_width * im_ratio)

        det_scale = float(new_height) / bgr.shape[0]
        resized_img = cv2.resize(bgr, (new_width, new_height))
        det_img = np.zeros((input_size[1], input_size[0], 3), dtype=np.uint8)
        det_img[:new_height, :new_width, :] = resized_img

        # Normalize and convert to NCHW float32
        blob = (det_img.astype(np.float32) - 127.5) / 128.0
        blob = blob[:, :, ::-1]  # BGR to RGB
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        # Run inference
        net_outs = self.session.run(self.output_names, {self.input_name: blob})

        scores_list = []
        bboxes_list = []
        kpss_list = []

        # Strides: 8, 16, 32
        for idx, stride in enumerate([8, 16, 32]):
            scores = net_outs[idx].ravel()
            bbox_preds = net_outs[idx + 3] * stride
            kps_preds = net_outs[idx + 6] * stride

            anchor_centers = self.anchors[stride]

            pos_inds = np.where(scores >= det_thresh)[0]
            if len(pos_inds) > 0:
                pos_scores = scores[pos_inds]
                pos_bbox_preds = bbox_preds[pos_inds]
                pos_kps_preds = kps_preds[pos_inds]
                pos_anchors = anchor_centers[pos_inds]

                bboxes = distance2bbox(pos_anchors, pos_bbox_preds)
                kpss = distance2kps(pos_anchors, pos_kps_preds).reshape((len(pos_inds), 5, 2))

                scores_list.append(pos_scores)
                bboxes_list.append(bboxes)
                kpss_list.append(kpss)

        if len(scores_list) == 0:
            return []

        all_scores = np.concatenate(scores_list)
        all_bboxes = np.vstack(bboxes_list) / det_scale
        all_kpss = np.vstack(kpss_list) / det_scale

        # Apply NMS
        keep = nms(all_bboxes, all_scores, thresh=0.4)
        if len(keep) == 0:
            return []

        keep_scores = all_scores[keep]
        keep_bboxes = all_bboxes[keep]
        keep_kpss = all_kpss[keep]

        detections = []
        for i in range(len(keep)):
            bbox_coords = keep_bboxes[i]
            x1 = max(0, round(bbox_coords[0]))
            y1 = max(0, round(bbox_coords[1]))
            x2 = min(bgr.shape[1], round(bbox_coords[2]))
            y2 = min(bgr.shape[0], round(bbox_coords[3]))

            # Compute blur_var and brightness on crop
            crop = bgr[y1:y2, x1:x2]
            if crop.size > 0:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                brightness = float(np.mean(gray))
            else:
                blur_var = 0.0
                brightness = 0.0

            detections.append(
                Detection(
                    bbox=(x1, y1, x2, y2),
                    det_score=float(keep_scores[i]),
                    landmarks=keep_kpss[i].astype(np.float32),
                    blur_var=blur_var,
                    brightness=brightness,
                )
            )

        detections.sort(key=lambda d: d.det_score, reverse=True)
        return detections
