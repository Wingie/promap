"""Benchmark: scipy reproject vs cv2.remap"""

import numpy as np
import time
import cv2
import scipy.interpolate

PROJ_W, PROJ_H = 1920, 1080
CAM_W, CAM_H = 1280, 720
N_RUNS = 10

# Simulate a lookup table (projector pixel -> camera pixel mapping)
# Smooth mapping with some distortion, like a real scene
print(f"Projector: {PROJ_W}x{PROJ_H}, Camera: {CAM_W}x{CAM_H}")
print(f"Generating synthetic lookup table...")

cx = np.linspace(50, CAM_W - 50, PROJ_W)
cy = np.linspace(50, CAM_H - 50, PROJ_H)
map_x, map_y = np.meshgrid(cx, cy)
# Add some barrel distortion
center_x, center_y = PROJ_W / 2, PROJ_H / 2
dx = (np.arange(PROJ_W) - center_x) / center_x
dy = (np.arange(PROJ_H) - center_y) / center_y
dx, dy = np.meshgrid(dx, dy)
r2 = dx**2 + dy**2
map_x += 20 * r2 * dx * (CAM_W / PROJ_W)
map_y += 15 * r2 * dy * (CAM_H / PROJ_H)

lookup = np.dstack((map_x, map_y)).astype(np.float64)

# Fake camera frame (color)
scene = np.random.randint(0, 255, (CAM_H, CAM_W, 3), dtype=np.uint8)

print()

# --- Benchmark scipy reproject (current implementation) ---
def scipy_reproject(lookup, im):
    def interp(grid):
        return scipy.interpolate.RegularGridInterpolator(
            [np.arange(d) for d in grid.shape[0:2]], grid
        )
    return interp(im)(lookup[:, :, 1::-1])

print("=== scipy RegularGridInterpolator (current) ===")
# Warmup
_ = scipy_reproject(lookup, scene)

times = []
for i in range(N_RUNS):
    t0 = time.perf_counter()
    result_scipy = scipy_reproject(lookup, scene)
    t1 = time.perf_counter()
    times.append(t1 - t0)
    print(f"  run {i+1}: {times[-1]*1000:.1f} ms")

avg_scipy = np.mean(times)
fps_scipy = 1.0 / avg_scipy
print(f"  avg: {avg_scipy*1000:.1f} ms  ({fps_scipy:.1f} FPS)")
print()

# --- Benchmark cv2.remap ---
map_x_f32 = map_x.astype(np.float32)
map_y_f32 = map_y.astype(np.float32)

print("=== cv2.remap ===")
# Warmup
_ = cv2.remap(scene, map_x_f32, map_y_f32, cv2.INTER_LINEAR)

times = []
for i in range(N_RUNS):
    t0 = time.perf_counter()
    result_cv2 = cv2.remap(scene, map_x_f32, map_y_f32, cv2.INTER_LINEAR)
    t1 = time.perf_counter()
    times.append(t1 - t0)
    print(f"  run {i+1}: {times[-1]*1000:.1f} ms")

avg_cv2 = np.mean(times)
fps_cv2 = 1.0 / avg_cv2
print(f"  avg: {avg_cv2*1000:.1f} ms  ({fps_cv2:.1f} FPS)")
print()

print(f"=== Summary ===")
print(f"  scipy:     {avg_scipy*1000:.1f} ms / frame  ({fps_scipy:.1f} FPS)")
print(f"  cv2.remap: {avg_cv2*1000:.1f} ms / frame  ({fps_cv2:.1f} FPS)")
print(f"  speedup:   {avg_scipy/avg_cv2:.0f}x")
