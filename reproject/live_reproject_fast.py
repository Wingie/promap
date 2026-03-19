"""Live reprojection using cv2.remap (fast version).

Side-by-side: raw webcam vs remapped with barrel distortion.
Press 'q' to quit.
"""

import numpy as np
import cv2
import time

CAM_INDEX = 0
PROJ_W, PROJ_H = 1920, 1080

cap = cv2.VideoCapture(CAM_INDEX)
if not cap.isOpened():
    raise RuntimeError("Could not open webcam")

cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Camera: {cam_w}x{cam_h}, Output: {PROJ_W}x{PROJ_H}")

# Build synthetic lookup table (projector -> camera coords)
cx = np.linspace(0, cam_w - 1, PROJ_W)
cy = np.linspace(0, cam_h - 1, PROJ_H)
map_x, map_y = np.meshgrid(cx, cy)

# Add barrel distortion
dx = (np.arange(PROJ_W) - PROJ_W / 2) / (PROJ_W / 2)
dy = (np.arange(PROJ_H) - PROJ_H / 2) / (PROJ_H / 2)
dx, dy = np.meshgrid(dx, dy)
r2 = dx**2 + dy**2
map_x += 200 * r2 * dx
map_y += 150 * r2 * dy
map_x = np.clip(map_x, 0, cam_w - 1)
map_y = np.clip(map_y, 0, cam_h - 1)

# cv2.remap needs float32
map_x = map_x.astype(np.float32)
map_y = map_y.astype(np.float32)

print(f"Lookup range X: {map_x.min():.0f} - {map_x.max():.0f}")
print(f"Lookup range Y: {map_y.min():.0f} - {map_y.max():.0f}")
print("Press 'q' to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    t0 = time.perf_counter()
    reprojected = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR)
    dt = time.perf_counter() - t0

    # Resize both to half for side-by-side display
    disp_w, disp_h = PROJ_W // 2, PROJ_H // 2
    raw_resized = cv2.resize(frame, (disp_w, disp_h))
    reproj_resized = cv2.resize(reprojected, (disp_w, disp_h))

    label = f"cv2.remap: {dt*1000:.1f}ms ({1/dt:.0f} FPS)"
    cv2.putText(reproj_resized, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(raw_resized, "raw", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    combined = np.hstack((raw_resized, reproj_resized))
    cv2.imshow("Live Reproject (cv2.remap)", combined)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
