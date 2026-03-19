# Promap Learnings

## What promap actually does

Promap is a **structured light scanning tool** that computes the geometric relationship between a projector and a camera using gray code patterns. It does NOT do segmentation or zone painting — that's a manual post-processing step.

### The pipeline

```
generate → project → capture → decode → invert → reproject
  (-g)      (-p)      (-c)      (-d)     (-i)      (-r)
```

1. **Generate**: Creates 24 gray code pattern images (for 1920x1080 projector)
2. **Project**: Displays patterns fullscreen on projector via PyQt5
3. **Capture**: Webcam captures each pattern (~1 min total, 2s per pattern + 5s warmup)
4. **Decode**: Thresholds + decodes gray codes → camera-to-projector lookup table
5. **Invert**: Inverts the lookup (projector-to-camera) + computes disparity/depth map
6. **Reproject**: Maps camera's view into projector space → `light.png` and `dark.png`

### What you get out of it

- `lookup.png` — the UV map (projector pixel → camera pixel mapping)
- `disparity.png` — coarse depth map
- `light.png` — the scene as the projector "sees" it
- `dark.png` — same but with lights off (the first captured frame)

### The full projection mapping workflow (with Radiance)

1. Run `promap -af -v` with projector + webcam → produces `light.png` + `lookup.png`
2. Open `light.png` in GIMP, paint colored zones to define projection regions
3. Import the zone map into [Radiance](https://radiance.video) as `uvmap` and `mask` inputs
4. Radiance maps live video content onto the physical object through the projector

## Benchmarks

Tested on macOS, 1920x1080 projector, 1280x720 camera:

| Method | Latency | FPS |
|---|---|---|
| `scipy.interpolate.RegularGridInterpolator` (current) | **424 ms** | 2.4 FPS |
| `cv2.remap` | **1.7 ms** | 603 FPS |

**256x speedup** with cv2.remap. scipy is fine for one-shot reprojection but unusable for real-time.

## Live reproject test

Tested live webcam → scipy reproject with synthetic barrel distortion lookup table at 640x480. Confirmed:
- The reproject math works correctly
- Distortion is visible at edges (barrel distortion applied)
- scipy manages ~2-3 FPS at 640x480 (too slow for real-time)

## Kinect v2 setup

libfreenect2 is built at `~/code/libfreenect2/` with Python bindings in the venv. The dylib isn't on the default path, so before using it:

```bash
export DYLD_LIBRARY_PATH=~/code/libfreenect2/build/lib
source ~/code/libfreenect2/venv/bin/activate
```

There's also `~/code/KinectV2_Syphon/` — an openFrameworks app that sends Kinect v2 to Syphon (makes it available as a video source to other macOS apps).

The Kinect is physically in the office — untested with promap so far.

## Key technical details

- Lookup images encode X in blue channel, Y in green channel (BGR format, OpenCV convention)
- Coordinates are normalized to uint16 by default (use `--unnormalized` for raw pixel coords)
- `cv2` is used at runtime but removed from pip dependencies due to install weirdness
- PyQt5 is required for the projection step (fullscreen display on secondary screen)
- The scan only needs to be redone when projector or objects move
