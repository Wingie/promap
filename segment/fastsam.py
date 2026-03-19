"""Live webcam segmentation with FastSAM + gradient compositing.

Uses FastSAM (via ultralytics) for real-time instance segmentation,
composites zone maps using compose_zone_map() from segment.py with
luminance-based gradient shading.

Side-by-side display: raw webcam | segmented overlay with FPS.
Press 'q' to quit.

Usage:
    python segment/fastsam.py
    python segment/fastsam.py --flat --max-zones 12
    python segment/fastsam.py --model FastSAM-x.pt --device cuda
    python segment/fastsam.py --benchmark -v
    python segment/fastsam.py --benchmark --preview-scale 0.5
"""

import argparse
import sys
import time

import cv2
import numpy as np

# Import compositing functions from segment.py (sibling module)
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segment import compose_zone_map, get_zone_color


def detect_device(requested=None):
    """Auto-detect best available device: cuda > mps > cpu."""
    if requested:
        return requested
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def convert_masks(mask_data, frame_shape):
    """Convert FastSAM mask tensors to segment.py format.

    FastSAM returns masks.data as torch tensor (N, H, W).
    Returns list of {"segmentation": bool_ndarray, "area": int} dicts,
    resized to match frame dimensions if needed.
    """
    masks_np = mask_data.cpu().numpy().astype(bool)
    frame_h, frame_w = frame_shape[:2]
    mask_h, mask_w = masks_np.shape[1], masks_np.shape[2]

    result = []
    for m in masks_np:
        if mask_h != frame_h or mask_w != frame_w:
            m = cv2.resize(m.astype(np.uint8), (frame_w, frame_h),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
        result.append({"segmentation": m, "area": int(m.sum())})

    result.sort(key=lambda x: x["area"], reverse=True)
    return result


class ZoneTracker:
    """Track zones across frames using IoU matching for stable color assignment."""

    def __init__(self, iou_threshold=0.3):
        self.prev_masks = []       # bool ndarrays from previous frame
        self.zone_ids = []         # parallel list of stable zone IDs
        self.next_id = 0
        self.iou_threshold = iou_threshold

    def update(self, masks):
        """Match new masks to previous frame via IoU, return stable zone IDs.

        Args:
            masks: list of {"segmentation": bool_ndarray, "area": int} dicts

        Returns:
            list of int zone IDs, parallel to input masks
        """
        new_segs = [m["segmentation"] for m in masks]
        n_new = len(new_segs)
        n_prev = len(self.prev_masks)

        if n_prev == 0 or n_new == 0:
            # First frame or no masks: assign fresh IDs
            ids = list(range(self.next_id, self.next_id + n_new))
            self.next_id += n_new
            self.prev_masks = new_segs
            self.zone_ids = ids
            return ids

        # Compute IoU matrix (n_new x n_prev)
        iou_matrix = np.empty((n_new, n_prev), dtype=np.float32)
        for i, ns in enumerate(new_segs):
            for j, ps in enumerate(self.prev_masks):
                intersection = np.count_nonzero(ns & ps)
                union = np.count_nonzero(ns | ps)
                iou_matrix[i, j] = intersection / union if union > 0 else 0.0

        # Greedy matching: best IoU first
        ids = [None] * n_new
        used_prev = set()
        used_new = set()

        # Flatten and sort all (i, j) pairs by IoU descending
        pairs = []
        for i in range(n_new):
            for j in range(n_prev):
                if iou_matrix[i, j] >= self.iou_threshold:
                    pairs.append((iou_matrix[i, j], i, j))
        pairs.sort(reverse=True)

        for _, i, j in pairs:
            if i in used_new or j in used_prev:
                continue
            ids[i] = self.zone_ids[j]
            used_new.add(i)
            used_prev.add(j)

        # Assign fresh IDs to unmatched new masks
        for i in range(n_new):
            if ids[i] is None:
                ids[i] = self.next_id
                self.next_id += 1

        self.prev_masks = new_segs
        self.zone_ids = ids
        self._last_iou_matrix = iou_matrix
        self._last_matched = len(used_new)
        self._last_fresh = n_new - len(used_new)
        return ids


def main():
    parser = argparse.ArgumentParser(
        description="Live webcam segmentation with FastSAM + gradient compositing")
    parser.add_argument("--cam", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--model", default="FastSAM-s.pt",
                        help="FastSAM model: FastSAM-s.pt or FastSAM-x.pt (default: FastSAM-s.pt)")
    parser.add_argument("--device", default=None,
                        help="Force device: cpu/cuda/mps (default: auto-detect)")
    parser.add_argument("--imgsz", type=int, nargs=2, default=[640, 480],
                        metavar=("W", "H"), help="Inference resolution (default: 640 480)")
    parser.add_argument("--conf", type=float, default=0.4,
                        help="Confidence threshold (default: 0.4)")
    parser.add_argument("--iou", type=float, default=0.9,
                        help="IoU threshold (default: 0.9)")
    parser.add_argument("--max-zones", type=int, default=8,
                        help="Max number of zones (default: 8)")
    parser.add_argument("--alpha", type=float, default=0.5,
                        help="Overlay opacity (default: 0.5)")
    parser.add_argument("--flat", action="store_true",
                        help="Disable gradient shading, use flat solid colors")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--benchmark", type=int, nargs="?", const=100, default=0,
                        metavar="N", help="Benchmark mode: run N frames (default 100), print stats, quit")
    parser.add_argument("--preview-scale", type=float, default=1.0,
                        help="Downscale factor for compositing (e.g. 0.5 = half res). Default: 1.0")
    args = parser.parse_args()

    device = detect_device(args.device)
    print(f"Device: {device}")
    print(f"Model: {args.model}")

    # Load FastSAM model
    from ultralytics import FastSAM
    model = FastSAM(args.model)

    # Open webcam
    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        print(f"Error: could not open camera {args.cam}")
        return 1

    cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera: {cam_w}x{cam_h}")
    print("Press 'q' to quit")

    benchmark = args.benchmark
    preview_scale = args.preview_scale

    if benchmark:
        print(f"Benchmark mode: {benchmark} frames")
    if preview_scale != 1.0:
        print(f"Preview scale: {preview_scale}")

    window_name = "Live Segment"
    if not benchmark:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    tracker = ZoneTracker()
    frame_times = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.perf_counter()

        # Optionally downscale for compositing
        if preview_scale != 1.0:
            comp_h = int(frame.shape[0] * preview_scale)
            comp_w = int(frame.shape[1] * preview_scale)
            comp_frame = cv2.resize(frame, (comp_w, comp_h), interpolation=cv2.INTER_LINEAR)
        else:
            comp_frame = frame

        # FastSAM inference
        results = model(comp_frame, device=device, retina_masks=False,
                        imgsz=tuple(args.imgsz), conf=args.conf, iou=args.iou,
                        verbose=False)

        # Convert masks and compose zone map
        if results[0].masks is not None:
            masks = convert_masks(results[0].masks.data, comp_frame.shape)
            masks = masks[:args.max_zones]
            n_masks = len(masks)

            zone_ids = tracker.update(masks)
            colors = [get_zone_color(zid) for zid in zone_ids]

            # Gradient from frame luminance
            gradient = None
            if not args.flat:
                gradient = cv2.cvtColor(comp_frame, cv2.COLOR_BGR2GRAY).astype(np.float32)

            zone_map = compose_zone_map(masks, colors, comp_frame.shape, disparity=gradient)
        else:
            zone_map = np.zeros((*comp_frame.shape[:2], 4), dtype=np.uint8)
            n_masks = 0

        # Upscale zone_map back to full res if needed
        if preview_scale != 1.0:
            zone_map = cv2.resize(zone_map, (frame.shape[1], frame.shape[0]),
                                  interpolation=cv2.INTER_LINEAR)

        dt = time.perf_counter() - t0

        # Alpha-blend overlay onto raw frame
        # zone_map is RGBA (RGB order from assign_colors), frame is BGR
        alpha_f32 = np.float32(args.alpha)
        alpha_mask = (zone_map[:, :, 3:].astype(np.float32) * (alpha_f32 / 255.0))
        overlay_bgr = zone_map[:, :, :3][:, :, ::-1].astype(np.float32)
        blended = (overlay_bgr * alpha_mask + frame.astype(np.float32) * (np.float32(1.0) - alpha_mask))
        blended = blended.astype(np.uint8)

        # FPS label
        fps = 1.0 / dt if dt > 0 else 0
        # Zone tracking debug info
        if args.verbose and hasattr(tracker, '_last_iou_matrix'):
            iou_m = tracker._last_iou_matrix
            best_ious = iou_m.max(axis=1).tolist() if iou_m.size else []
            z_ids = tracker.zone_ids
            print(f"\n  zones:{n_masks} matched:{tracker._last_matched} fresh:{tracker._last_fresh} "
                  f"bestIoU:{[f'{v:.2f}' for v in best_ious]} ids:{z_ids}", flush=True)

        label = f"FastSAM: {dt*1000:.1f}ms ({fps:.0f} FPS) | {n_masks} zones"

        if benchmark:
            frame_times.append(dt)
            if args.verbose:
                print(f"\r  frame {len(frame_times)}/{benchmark}: {label}", end="", flush=True)
            if len(frame_times) >= benchmark:
                break
        else:
            cv2.putText(blended, label, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, "raw", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            if args.verbose:
                print(f"\r{label}", end="", flush=True)

            # Side-by-side display
            combined = np.hstack([frame, blended])
            cv2.imshow(window_name, combined)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    if args.verbose:
        print()

    cap.release()
    if not benchmark:
        cv2.destroyAllWindows()

    # Print benchmark results
    if benchmark and frame_times:
        times_ms = np.array(frame_times) * 1000
        avg = np.mean(times_ms)
        mn = np.min(times_ms)
        mx = np.max(times_ms)
        med = np.median(times_ms)
        print(f"\n--- Benchmark Results ({len(frame_times)} frames) ---")
        print(f"  Avg: {avg:.1f} ms  ({1000/avg:.1f} FPS)")
        print(f"  Min: {mn:.1f} ms  ({1000/mn:.1f} FPS)")
        print(f"  Max: {mx:.1f} ms  ({1000/mx:.1f} FPS)")
        print(f"  Med: {med:.1f} ms  ({1000/med:.1f} FPS)")
        print(f"  Settings: imgsz={args.imgsz}, conf={args.conf}, "
              f"flat={args.flat}, preview_scale={preview_scale}")

    return 0


if __name__ == "__main__":
    exit(main() or 0)
