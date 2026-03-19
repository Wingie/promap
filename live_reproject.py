"""Live reprojection test using scipy (current implementation).

Uses a webcam feed and a synthetic lookup table to verify
reprojection works end-to-end before swapping in cv2.remap.
"""

import numpy as np
import cv2
import time
from promap.reproject import reproject

CAM_INDEX = 0
PROJ_W, PROJ_H = 640, 480  # smaller for scipy speed

cap = cv2.VideoCapture(CAM_INDEX)
if not cap.isOpened():
    raise RuntimeError("Could not open webcam")

cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Camera: {cam_w}x{cam_h}, Output: {PROJ_W}x{PROJ_H}")

# Build a synthetic lookup table (projector -> camera coords)
cx = np.linspace(0, cam_w - 1, PROJ_W)
cy = np.linspace(0, cam_h - 1, PROJ_H)
map_x, map_y = np.meshgrid(cx, cy)

# Add barrel distortion so it's visually obvious it's working
dx = (np.arange(PROJ_W) - PROJ_W / 2) / (PROJ_W / 2)
dy = (np.arange(PROJ_H) - PROJ_H / 2) / (PROJ_H / 2)
dx, dy = np.meshgrid(dx, dy)
r2 = dx**2 + dy**2
map_x += 200 * r2 * dx
map_y += 150 * r2 * dy
map_x = np.clip(map_x, 0, cam_w - 1)
map_y = np.clip(map_y, 0, cam_h - 1)

lookup = np.dstack((map_x, map_y))

# Verify distortion is present
print(f"Lookup range X: {map_x.min():.0f} - {map_x.max():.0f} (cam width {cam_w})")
print(f"Lookup range Y: {map_y.min():.0f} - {map_y.max():.0f} (cam height {cam_h})")
print(f"Max distortion X: {(200 * r2 * dx).max():.0f}px, Y: {(150 * r2 * dy).max():.0f}px")
print("Press 'q' to quit")
print("Left = raw webcam, Right = scipy reproject (barrel distortion)")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    t0 = time.perf_counter()
    reprojected = reproject(lookup, frame).astype(np.uint8)
    dt = time.perf_counter() - t0

    # Resize raw frame to match output size for side-by-side
    raw_resized = cv2.resize(frame, (PROJ_W, PROJ_H))

    # Add FPS text
    label = f"scipy: {dt*1000:.0f}ms ({1/dt:.1f} FPS)"
    cv2.putText(reprojected, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(raw_resized, "raw", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    combined = np.hstack((raw_resized, reprojected))
    cv2.imshow("Live Reproject Test (scipy)", combined)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
