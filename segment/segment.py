"""
Auto-segment promap zones using Meta's Segment Anything Model (SAM).

Generates colored zone maps from light.png for use in projection mapping
workflows (e.g. Radiance), replacing manual GIMP painting.
"""

import argparse
import logging
import os
import numpy as np
import cv2

logger = logging.getLogger(__name__)


def load_sam_model(checkpoint, model_type="vit_b", device=None):
    """Load SAM model, auto-detecting device (MPS > CUDA > CPU)."""
    import torch
    from segment_anything import sam_model_registry

    if device is None:
        # SAM v1 uses float64 ops which MPS doesn't support, so skip MPS
        if torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
    logger.info("Using device: %s", device)

    if not os.path.isfile(checkpoint):
        logger.info("Checkpoint not found at %s, attempting download...", checkpoint)
        _download_checkpoint(checkpoint, model_type)

    sam = sam_model_registry[model_type](checkpoint=checkpoint)
    sam.to(device=device)
    return sam


def _download_checkpoint(checkpoint, model_type):
    """Download SAM checkpoint from Meta's GitHub releases."""
    import urllib.request

    urls = {
        "vit_b": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
        "vit_l": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth",
        "vit_h": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
    }
    url = urls.get(model_type)
    if url is None:
        raise ValueError(f"Unknown model type: {model_type}. Choose from: {list(urls.keys())}")

    logger.info("Downloading %s checkpoint from %s", model_type, url)
    os.makedirs(os.path.dirname(checkpoint) or ".", exist_ok=True)
    urllib.request.urlretrieve(url, checkpoint)
    logger.info("Downloaded checkpoint to %s", checkpoint)


def generate_masks(image, sam_model, min_area=1000):
    """Run SamAutomaticMaskGenerator and return filtered masks sorted by area."""
    from segment_anything import SamAutomaticMaskGenerator

    generator = SamAutomaticMaskGenerator(
        model=sam_model,
        min_mask_region_area=min_area,
    )
    logger.info("Generating masks...")
    masks = generator.generate(image)
    logger.info("SAM generated %d raw masks", len(masks))

    # Filter by stability score
    masks = [m for m in masks if m["stability_score"] > 0.8]
    logger.info("%d masks after stability filtering", len(masks))

    # Filter by minimum area
    masks = [m for m in masks if m["area"] >= min_area]
    logger.info("%d masks after area filtering (min_area=%d)", len(masks), min_area)

    # Sort by area, largest first
    masks.sort(key=lambda m: m["area"], reverse=True)
    return masks


def filter_by_disparity(masks, disparity, threshold_fraction=0.1):
    """Remove background masks using disparity (depth) image.

    Masks whose mean disparity is below threshold_fraction of the max
    disparity are considered background and removed. Adjacent masks
    at similar depths are merged.
    """
    max_disp = np.amax(disparity)
    if max_disp == 0:
        logger.warning("Disparity image is all zeros, skipping depth filtering")
        return masks

    threshold = threshold_fraction * max_disp
    filtered = []
    for m in masks:
        seg = m["segmentation"]
        mean_disp = np.mean(disparity[seg])
        if mean_disp >= threshold:
            filtered.append(m)
        else:
            logger.debug("Removing mask (area=%d) with mean disparity %.1f < threshold %.1f",
                         m["area"], mean_disp, threshold)

    logger.info("%d masks after disparity filtering (threshold=%.1f)", len(filtered), threshold)

    # Merge adjacent masks at similar depths
    filtered = _merge_similar_depth(filtered, disparity, depth_tolerance=0.15 * max_disp)
    return filtered


def _merge_similar_depth(masks, disparity, depth_tolerance):
    """Merge masks that are spatially adjacent and at similar depths."""
    if len(masks) <= 1:
        return masks

    merged = list(masks)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged):
            j = i + 1
            while j < len(merged):
                seg_i = merged[i]["segmentation"]
                seg_j = merged[j]["segmentation"]

                # Check depth similarity
                mean_i = np.mean(disparity[seg_i])
                mean_j = np.mean(disparity[seg_j])
                if abs(mean_i - mean_j) > depth_tolerance:
                    j += 1
                    continue

                # Check adjacency via dilation
                dilated = cv2.dilate(seg_i.astype(np.uint8), np.ones((5, 5), np.uint8))
                if not np.any(dilated & seg_j.astype(np.uint8)):
                    j += 1
                    continue

                # Merge
                new_seg = seg_i | seg_j
                merged[i] = {
                    "segmentation": new_seg,
                    "area": int(np.sum(new_seg)),
                    "stability_score": min(merged[i]["stability_score"], merged[j]["stability_score"]),
                }
                merged.pop(j)
                changed = True
                logger.debug("Merged two masks at similar depth (%.1f, %.1f)", mean_i, mean_j)
            i += 1

    logger.info("%d masks after depth-based merging", len(merged))
    return merged


def assign_colors(n):
    """Generate n maximally distinct colors via HSV spacing."""
    colors = []
    for i in range(n):
        hue = int(180 * i / n)  # OpenCV hue range is 0-179
        hsv = np.array([[[hue, 255, 255]]], dtype=np.uint8)
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
        # Return as RGBA
        colors.append((int(bgr[2]), int(bgr[1]), int(bgr[0]), 255))
    return colors


# Fixed palette of 16 maximally-spaced RGBA colors for stable zone coloring
ZONE_PALETTE = assign_colors(16)


def get_zone_color(zone_id):
    """Return a stable RGBA color for a given zone ID."""
    return ZONE_PALETTE[zone_id % len(ZONE_PALETTE)]


def compose_zone_map(masks, colors, shape, disparity=None):
    """Paint segments on an RGBA canvas with optional disparity-based gradients.

    Largest segments painted first, smaller on top.
    If disparity is provided, each zone's RGB is modulated by its normalized
    disparity values (range 0.3–1.0) to create depth-based luminosity gradients.
    """
    h, w = shape[:2]
    canvas = np.zeros((h, w, 4), dtype=np.uint8)

    for mask, color in zip(masks, colors):
        seg = mask["segmentation"]
        if disparity is not None:
            zone_disp = disparity[seg]
            lo, hi = zone_disp.min(), zone_disp.max()
            if hi > lo:
                norm = (zone_disp - lo) / (hi - lo)
            else:
                norm = np.ones_like(zone_disp, dtype=np.float32)
            brightness = np.float32(0.3) + np.float32(0.7) * norm
            color_array = np.array(color[:3], dtype=np.float32)
            canvas[seg, :3] = (color_array * brightness[:, np.newaxis]).astype(np.uint8)
            canvas[seg, 3] = 255
        else:
            canvas[seg] = color

    return canvas


def save_individual_masks(masks, output_dir):
    """Save per-zone binary PNG masks."""
    os.makedirs(output_dir, exist_ok=True)
    for i, mask in enumerate(masks):
        seg = mask["segmentation"].astype(np.uint8) * 255
        fn = os.path.join(output_dir, f"zone_{i:03d}.png")
        if not cv2.imwrite(fn, seg):
            logger.error("Could not write %s", fn)
        else:
            logger.debug("Saved mask %s", fn)
    logger.info("Saved %d individual masks to %s", len(masks), output_dir)


def main():
    logging.basicConfig()

    parser = argparse.ArgumentParser(
        prog="segment_zones",
        description="Auto-segment promap scenes into projection zones using SAM.",
    )
    parser.add_argument("--input", "-I", required=True, help="Input image (e.g. light.png)")
    parser.add_argument("--output", "-O", default="zones.png", help="Output zone map (RGBA PNG)")
    parser.add_argument("--disparity", help="Optional disparity image for depth filtering")
    parser.add_argument("--checkpoint", default="sam_vit_b_01ec64.pth",
                        help="SAM checkpoint path (auto-downloads if missing)")
    parser.add_argument("--model-type", default="vit_b", choices=["vit_b", "vit_l", "vit_h"],
                        help="SAM model type: vit_b (fast), vit_l, vit_h (best)")
    parser.add_argument("--device", default=None, help="Force device (mps/cuda/cpu)")
    parser.add_argument("--max-zones", type=int, default=8, help="Maximum number of zones")
    parser.add_argument("--min-area", type=int, default=1000, help="Minimum mask area in pixels")
    parser.add_argument("--individual-masks", action="store_true",
                        help="Also save per-zone binary mask PNGs")
    parser.add_argument("--flat", action="store_true",
                        help="Disable gradient shading, use flat solid colors")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Load input image
    image_bgr = cv2.imread(args.input)
    if image_bgr is None:
        logger.error("Could not read input image: %s", args.input)
        return 1
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    logger.info("Loaded input image: %s (%dx%d)", args.input, image_bgr.shape[1], image_bgr.shape[0])

    # Load SAM model
    sam = load_sam_model(args.checkpoint, args.model_type, args.device)

    # Generate masks
    masks = generate_masks(image_rgb, sam, min_area=args.min_area)

    if not masks:
        logger.error("No masks generated. Try lowering --min-area.")
        return 1

    # Optional disparity filtering
    disp_img = None
    if args.disparity:
        disp_img = cv2.imread(args.disparity, cv2.IMREAD_GRAYSCALE)
        if disp_img is None:
            logger.error("Could not read disparity image: %s", args.disparity)
            return 1
        if disp_img.shape[:2] != image_bgr.shape[:2]:
            logger.warning("Disparity image size mismatch, resizing to match input")
            disp_img = cv2.resize(disp_img, (image_bgr.shape[1], image_bgr.shape[0]))
        masks = filter_by_disparity(masks, disp_img.astype(np.float64))

    # Cap at max zones
    masks = masks[:args.max_zones]
    logger.info("Using %d zones", len(masks))

    # Assign colors and compose
    colors = assign_colors(len(masks))

    # Determine gradient source
    gradient = None
    if not args.flat:
        if args.disparity and disp_img is not None:
            gradient = disp_img.astype(np.float64)
            logger.info("Using disparity image for gradient shading")
        else:
            gradient = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float64)
            logger.info("Using input image luminance for gradient shading")

    zone_map = compose_zone_map(masks, colors, image_bgr.shape, disparity=gradient)

    # Save output
    if not cv2.imwrite(args.output, cv2.cvtColor(zone_map, cv2.COLOR_RGBA2BGRA)):
        logger.error("Could not write output: %s", args.output)
        return 1
    logger.info("Saved zone map: %s", args.output)

    # Save individual masks
    if args.individual_masks:
        output_dir = os.path.splitext(args.output)[0] + "_masks"
        save_individual_masks(masks, output_dir)

    return 0


if __name__ == "__main__":
    exit(main() or 0)
