# Kinect v2 + TouchDesigner Integration Plan (macOS)

## Project Goal
Connect working Kinect v2 (via libfreenect2/pylibfreenect2) to TouchDesigner on macOS for real-time hand/body tracking to control Ableton Live music parameters - adapting the Windows-based "Hand-Controlled Operators" project to work on Mac.

## Current Status

### ✅ What's Working
- **libfreenect2**: Successfully compiled and running on macOS
- **pylibfreenect2**: Python bindings installed and functional
- **Data Streams Available**:
  - RGB: 1920×1080, 30fps, BGRA format
  - Depth: 512×424, 30fps, float32 (millimeters)
  - IR: 424×512, 30fps, float32
  - Point Cloud: Full 3D coordinates (X, Y, Z) + RGB colors
- **Working Example**: `pylibfreenect2/examples/artistic_point_cloud_cv.py`
  - Real-time point cloud visualization
  - Multiple artistic rendering modes
  - Camera intrinsics: fx, fy, cx, cy available
  - Gesture recognition examples available
- **TouchDesigner + Ableton Setup**: Working on Mac
  - TDAbleton connection functional
  - Ableton Live 11 Suite + latest TouchDesigner
  - Reference project: "Hand-Controlled Operators" (Windows-based, uses native Kinect CHOP)

### ❌ The Problem
- Microsoft never released Kinect v2 drivers for macOS
- TouchDesigner's native Kinect v2 CHOP/TOP doesn't work on Mac
- Reference project (`/Users/wingston/code/abletonlive/TD/new/Ki+TD+AL Instrument - Hand Controlled Operators/`) was built for Windows
- Need custom bridge between Python (Kinect data) → TouchDesigner → Ableton Live

### 🎯 End Goal
Recreate the "Hand-Controlled Operators" functionality on Mac:
- Hand/body tracking via Kinect → Hand position/gesture data → TouchDesigner MathCHOP logic → Ableton_Parameter components → Ableton Live instrument/effect controls

---

## Proposed Solution: Hybrid Syphon + OSC Architecture

### Why This Approach?
1. **Syphon** is native to macOS (GPU texture sharing, zero latency)
2. **OSC** is simple, real-time, and widely supported
3. TouchDesigner has native Syphon In TOP and OSC In CHOP/DAT
4. Leverages existing working Python code

### Data Flow Diagram
```
Kinect v2 Sensor
       ↓
pylibfreenect2 (Python)
  - Hand tracking/gesture recognition
  - Point cloud analysis
       ↓
   ┌───┴───┐
   ↓       ↓
Syphon    OSC
(RGB +    (Hand X, Y, Z positions
 Depth     Gesture states
 visual)   Control values)
   ↓       ↓
TouchDesigner ✓ (Syphon In available!)
  - MathCHOP processing
  - Ableton_Parameter mapping
       ↓
   TDAbleton
       ↓
  Ableton Live 11
  - Instrument parameters
  - Effect controls
  - Musical output
```

---

## Hand Tracking & Gesture Recognition

### Available Hand Tracking from Kinect
Your `gesture_recognition.py` example already implements:

1. **Hand Detection** (depth-based)
   - Filter depth range (500-800mm) to isolate hand
   - Morphological operations to remove noise
   - Contour detection to find hand blob
   - Area filtering (1000-15000 pixels) to validate hand size

2. **Hand Position Tracking**
   - Centroid (X, Y) in depth image coordinates
   - Depth (Z) from median depth value
   - Convert to real-world 3D coordinates using camera intrinsics

3. **Gesture Recognition Features**
   - Contour area (hand size changes = open/closed hand)
   - Convexity ratio (finger extension detection)
   - Motion tracking (swipe left/right/up/down)
   - Gesture history buffer (temporal patterns)

### Data to Send to TouchDesigner

For hand-controlled music parameters, we'll extract and send:

**Primary Control Values** (via OSC):
- `/hand/position/x` - Hand X position (-1 to 1, normalized)
- `/hand/position/y` - Hand Y position (-1 to 1, normalized)
- `/hand/position/z` - Hand depth (normalized distance from sensor)
- `/hand/open` - Hand openness (0.0 = closed fist, 1.0 = open palm)
- `/hand/present` - Boolean (hand detected or not)

**Gesture Events** (via OSC):
- `/gesture/swipe_left` - Trigger event
- `/gesture/swipe_right` - Trigger event
- `/gesture/swipe_up` - Trigger event
- `/gesture/swipe_down` - Trigger event
- `/gesture/wave` - Trigger event
- `/gesture/clap` - Trigger event (two hands)

**Visual Feedback** (via Syphon):
- RGB camera view with hand overlay
- Depth visualization with hand detection mask
- Debug view showing tracking points

### Matching Windows Kinect CHOP Output

The Windows Kinect CHOP in TouchDesigner outputs channels like:
- `kinect/body/hand_left/x`, `y`, `z`
- `kinect/body/hand_right/x`, `y`, `z`
- `kinect/body/hand_left/state` (open/closed/lasso)
- `kinect/body/hand_right/state`

We'll replicate this structure with OSC channel naming for easy drop-in replacement in the existing TouchDesigner project.

---

## Technical Architecture

### Python Side: Kinect Data Publisher

#### Components to Build
1. **`kinect_to_touchdesigner.py`** - Main bridge script
   - Initialize Kinect (like `artistic_point_cloud_cv.py`)
   - Publish RGB + Depth via Syphon
   - Publish point cloud + metadata via OSC

2. **Data Streams**:

   **Stream 1: Syphon Textures**
   - RGB texture (1920×1080, BGRA)
   - Depth texture (512×424, encoded as grayscale or RGB colormap)
   - Uses: `syphonpy` or PyOpenGL + Syphon framework

   **Stream 2: OSC Messages**
   - Point cloud data (downsampled)
     - Format: `/kinect/pointcloud X Y Z R G B` (one point per message)
     - OR: `/kinect/pointcloud/batch [X1,Y1,Z1,R1,G1,B1, X2,Y2,Z2,...]` (bundled)
   - Metadata:
     - `/kinect/fps` - Current framerate
     - `/kinect/depth_range` - Min/max depth values
     - `/kinect/point_count` - Number of points in cloud
     - `/kinect/camera_params` - fx, fy, cx, cy (once on startup)

#### Required Python Libraries
```bash
pip install python-osc      # OSC communication
pip install syphonpy         # Syphon texture sharing (if available)
# OR use PyOpenGL + Syphon framework (might need ctypes wrapper)
```

### TouchDesigner Side: Data Receiver

#### Network Setup
- **Syphon In TOP**: Receive RGB and Depth textures
  - RGB Server Name: `"Kinect_RGB"`
  - Depth Server Name: `"Kinect_Depth"`

- **OSC In CHOP** or **OSC In DAT**: Receive point cloud
  - Port: `7400` (default, configurable)
  - Protocol: UDP
  - Address patterns: `/kinect/*`

#### Data Processing Chain

**Option A: Use Syphon Depth Texture to Generate Point Cloud**
```
Syphon In TOP (Depth)
    → TOP to CHOP (read depth values)
    → Script CHOP/SOP (reconstruct 3D using camera intrinsics)
    → Add SOP (create point geometry)
    → Color from Syphon RGB texture
```

**Option B: Use OSC Point Cloud Directly**
```
OSC In DAT (receive point cloud)
    → DAT to CHOP (parse X,Y,Z,R,G,B)
    → CHOP to SOP (create 3D points)
    → Point instancing or particle system
```

**Option C: Hybrid (Recommended)**
- Use Syphon for 2D visualization (fast preview)
- Use OSC for downsampled 3D point cloud (interactive control)
- Switch based on performance needs

---

## Implementation Steps

### Phase 1: Basic Connection Test
**Goal**: Verify Syphon and OSC communication works

1. **Python Test Script**: `test_syphon_osc.py`
   - Send a static image via Syphon
   - Send test OSC messages
   - Verify TouchDesigner receives both

2. **TouchDesigner Test Network**
   - Create Syphon In TOP
   - Create OSC In DAT
   - Display received data

**Success Criteria**: See test image in TD, see OSC messages in DAT

---

### Phase 2: Kinect RGB + Depth Streaming
**Goal**: Stream live Kinect camera feeds to TouchDesigner

1. **Python Script**: `kinect_rgb_depth_streamer.py`
   - Based on `multiframe_listener.py`
   - Add Syphon server for RGB texture
   - Add Syphon server for Depth texture (convert depth float32 → normalized grayscale)

2. **TouchDesigner Network**
   - Two Syphon In TOPs (RGB and Depth)
   - Display side-by-side
   - Add false color mapping to depth (e.g., Ramp TOP)

**Success Criteria**: 30fps RGB + Depth streams in TouchDesigner

---

### Phase 3: Point Cloud via OSC
**Goal**: Send 3D point cloud data to TouchDesigner

1. **Python Script Enhancement**
   - Calculate 3D points (X, Y, Z) like in `artistic_point_cloud_cv.py` lines 424-441
   - Downsample point cloud (e.g., `point_step = 10`)
   - Send via OSC (bundle format for efficiency)
   - Use OSC bundles: send multiple messages per frame to avoid flooding

2. **TouchDesigner Network**
   - OSC In DAT to receive point cloud
   - Python DAT to parse and convert to table (X, Y, Z, R, G, B columns)
   - Table DAT → CHOP → SOP pipeline
   - Render as point cloud (Point SOP + Material)

**Performance Considerations**:
- Full resolution = 512×424 = 217,088 points (too much for OSC)
- With `point_step=10`: ~2,170 points (manageable)
- With `point_step=20`: ~540 points (very responsive)
- Test different step sizes for performance vs. quality

**Success Criteria**: 3D point cloud visible in TouchDesigner, rotatable

---

### Phase 4: Depth Texture to Point Cloud (Alternative)
**Goal**: Use GPU to reconstruct point cloud from depth texture

1. **TouchDesigner GLSL Shader Approach**
   - Depth texture → GLSL Shader
   - For each pixel (x, y) in depth texture:
     - Read depth value Z
     - Calculate X = (x - cx) * Z / fx
     - Calculate Y = (y - cy) * Z / fy
   - Output to geometry buffer (Render SOP or Texture 3D)

2. **Camera Intrinsics**
   - Send via OSC once: fx, fy, cx, cy
   - Store in TouchDesigner as constants
   - Use in GLSL shader

**Advantages**:
- GPU-accelerated (very fast)
- Full resolution point cloud (217k points)
- No network bandwidth issues

**Success Criteria**: Full-resolution point cloud from depth texture

---

### Phase 5: Interactive Controls
**Goal**: Control Kinect parameters from TouchDesigner

1. **Bi-directional OSC**
   - TouchDesigner → Python control messages:
     - `/kinect/point_step` (change point cloud density)
     - `/kinect/depth_range` (min/max depth filter)
     - `/kinect/color_mode` (RGB, thermal, etc.)
   - Python listens for OSC commands and adjusts

2. **TouchDesigner UI**
   - Sliders for depth range
   - Buttons for visualization modes
   - FPS display

**Success Criteria**: Change parameters in TD, see Kinect update in real-time

---

### Phase 6: Performance Optimization
**Goal**: Achieve stable 30fps with minimal latency

1. **Python Optimizations**
   - Use NumPy vectorization (already done in examples)
   - Async OSC sending (thread pool)
   - Syphon texture uploads on separate thread

2. **TouchDesigner Optimizations**
   - Use Instancing for point cloud rendering
   - LOD system (switch between detail levels based on camera distance)
   - Particle GPU for large point clouds

3. **Profiling**
   - Measure Python frame time
   - Measure TouchDesigner cook time
   - Identify bottlenecks

**Success Criteria**: Stable 30fps, <50ms latency

---

### Phase 7: Advanced Features (Optional)
1. **Gesture Recognition**
   - Adapt `gesture_recognition.py` example
   - Send gesture events via OSC (hand tracking, body skeleton)

2. **Recording/Playback**
   - Record Kinect streams to files
   - Playback for development without hardware

3. **Multi-Kinect Support**
   - Multiple Syphon servers (unique names)
   - Multiple OSC ports

---

## Technical Challenges & Solutions

### Challenge 1: Syphon Library for Python
**Problem**: `syphonpy` may not be available or maintained

**Solutions**:
1. **Option A**: Use `syphonpy` if available
   ```bash
   pip install syphonpy
   ```

2. **Option B**: Use PyOpenGL + Syphon Framework (ctypes)
   - Load Syphon.framework on Mac
   - Create OpenGL context
   - Share texture via Syphon server
   - Reference: https://github.com/Syphon/Python

3. **Option C**: Use Processing + Syphon
   - Write Processing sketch to read from Python (via files/OSC)
   - Use Processing's Syphon library
   - Acts as middle layer

4. **Option D**: Skip Syphon, use only OSC
   - Send RGB frame as JPEG/PNG via OSC (Base64 encoded)
   - Higher latency but simpler

### Challenge 2: OSC Message Size Limits
**Problem**: OSC messages have practical size limits (~64KB)

**Solutions**:
1. Send point cloud in multiple bundled messages
2. Use OSC blob type for binary data
3. Compress data (e.g., quantize float32 to int16)
4. Use ZeroMQ instead of OSC for large data

### Challenge 3: Coordinate System Differences
**Problem**: Kinect, OpenCV, OpenGL, TouchDesigner may use different coordinate systems

**Solutions**:
1. Document coordinate systems:
   - Kinect: +Z away from camera, +Y down, +X right
   - TouchDesigner: +Y up, +Z up (camera), +X right
2. Apply transformation matrix in TD
3. Test with known reference object (cube, checkboard)

### Challenge 4: Color Space and Formats
**Problem**: BGRA vs RGBA, color range 0-255 vs 0-1

**Solutions**:
1. Convert in Python before sending
2. Use TouchDesigner Shuffle TOP to reorder channels
3. Document format expectations

---

## File Structure

```
/Users/wingston/code/libfreenect2/
├── pylibfreenect2/
│   ├── examples/
│   │   ├── artistic_point_cloud_cv.py    # Working reference
│   │   ├── multiframe_listener.py         # Working reference
│   │   └── point_cloud.py                 # Working reference
│   └── touchdesigner_bridge/              # NEW: TD integration code
│       ├── kinect_to_touchdesigner.py     # Main bridge script
│       ├── test_syphon_osc.py             # Test/debug script
│       ├── kinect_syphon_server.py        # Syphon streaming module
│       ├── kinect_osc_sender.py           # OSC sending module
│       └── config.json                     # Configuration file
├── touchdesigner_projects/                 # NEW: TD project files
│   ├── kinect_receiver_basic.toe          # Phase 2: RGB + Depth
│   ├── kinect_pointcloud_osc.toe          # Phase 3: OSC point cloud
│   ├── kinect_pointcloud_gpu.toe          # Phase 4: GPU reconstruction
│   └── kinect_interactive.toe             # Phase 5: Full interactive
└── PLAN.md                                 # This file
```

---

## Dependencies & Installation

### Python Requirements
```bash
# Already installed
pip install numpy opencv-python pylibfreenect2

# New requirements
pip install python-osc           # OSC communication
pip install syphonpy             # Try this first (may not work)
# OR manually integrate Syphon framework

# Optional
pip install pyzmq                # Alternative to OSC for high bandwidth
pip install msgpack              # Efficient serialization
```

### TouchDesigner Requirements
- TouchDesigner version: 2023.x or later (free non-commercial license)
- macOS version: 10.14+ (for Syphon support)
- No additional plugins needed (Syphon and OSC are built-in)

### System Requirements
- macOS with Metal support
- USB 3.0 port for Kinect
- 8GB+ RAM recommended
- Dedicated GPU recommended for point cloud rendering

---

## Testing Strategy

### Unit Tests
1. **Test Syphon Server** (Python standalone)
   - Send test pattern texture
   - Verify in Syphon Recorder app

2. **Test OSC Sender** (Python standalone)
   - Send test messages
   - Verify in OSC monitor app (e.g., Protocol)

3. **Test TouchDesigner Receivers** (TD standalone)
   - Receive from test applications
   - Verify parsing and display

### Integration Tests
1. **RGB Stream Test**
   - Send Kinect RGB via Syphon
   - Display in TD, verify colors

2. **Depth Stream Test**
   - Send Kinect depth via Syphon
   - Display in TD, verify depth encoding

3. **Point Cloud Test**
   - Send downsampled point cloud via OSC
   - Display in TD, verify 3D geometry

4. **Latency Test**
   - Measure end-to-end latency (Kinect → TD display)
   - Target: <100ms

### Performance Tests
1. **FPS Test**: Maintain 30fps for 5 minutes
2. **CPU Usage**: Monitor Python and TD CPU usage
3. **Memory Test**: Check for memory leaks over time
4. **Network Bandwidth**: Monitor OSC message rate and size

---

## Alternative Approaches (If Primary Plan Fails)

### Fallback 1: WebSocket Instead of OSC
- Use WebSocket server in Python
- TouchDesigner WebSocket DAT
- Send JSON or binary data
- Pro: Better for large messages
- Con: More complex setup

### Fallback 2: File-Based Communication
- Python writes point cloud to temp file (PLY/OBJ format)
- TouchDesigner reads with File In SOP
- Use watchdog to monitor file changes
- Pro: Simple, debuggable
- Con: High disk I/O, latency

### Fallback 3: NDI (Network Device Interface)
- Use NDI for video streaming (RGB + Depth)
- TouchDesigner has NDI In TOP
- Pro: Industry standard, high quality
- Con: Requires NDI SDK, more setup

### Fallback 4: TouchDesigner Python SOP
- Run Kinect capture directly inside TouchDesigner's Python
- No external process needed
- Pro: Integrated solution
- Con: pylibfreenect2 may not work inside TD Python

---

## Timeline Estimate

| Phase | Task | Estimated Time |
|-------|------|---------------|
| 1 | Basic connection test (Syphon + OSC) | 2-4 hours |
| 2 | RGB + Depth streaming | 4-6 hours |
| 3 | Point cloud via OSC | 6-8 hours |
| 4 | Depth texture to point cloud (GPU) | 8-10 hours |
| 5 | Interactive controls | 4-6 hours |
| 6 | Performance optimization | 6-10 hours |
| 7 | Advanced features (optional) | 10-20 hours |
| **Total** | **Core functionality (Phase 1-5)** | **24-34 hours** |

---

## Resources & References

### Documentation
- **libfreenect2**: https://github.com/OpenKinect/libfreenect2
- **pylibfreenect2**: https://github.com/r9y9/pylibfreenect2
- **TouchDesigner**: https://derivative.ca/documentation
- **Syphon**: http://syphon.v002.info/
- **python-osc**: https://pypi.org/project/python-osc/

### Example Projects
- Syphon + TouchDesigner: https://derivative.ca/UserGuide/Syphon_Spout_In_TOP
- OSC + TouchDesigner: https://derivative.ca/UserGuide/OSC_In_CHOP
- Kinect Point Cloud Reconstruction: Various Processing examples

### Community
- TouchDesigner Forum: https://forum.derivative.ca/
- OpenKinect Community: https://openkinect.org/

---

## Next Steps

1. **Review this plan** - Discuss approach and priorities
2. **Set up development environment** - Verify all tools installed
3. **Start with Phase 1** - Test basic Syphon + OSC communication
4. **Iterate through phases** - Test and validate each step
5. **Document findings** - Update this plan based on learnings

---

## Notes & Observations

- Your `artistic_point_cloud_cv.py` already has excellent point cloud processing code
- Your `gesture_recognition.py` has working hand tracking and gesture detection
- Camera intrinsics are readily available from `device.getIrCameraParams()`
- The registration system (RGB to Depth alignment) is working
- Downsampling logic (`point_step`) is already implemented
- TouchDesigner already has Syphon In TOP available (confirmed by user)
- TDAbleton connection is working for controlling Ableton Live
- You have a reference Windows project showing the desired end behavior

**Key Insights**:
1. You've already solved the hard problem (getting Kinect working on Mac)
2. The bridge to TouchDesigner is mostly about data transport and format conversion
3. The gesture recognition code can be adapted for music control
4. The existing TD → Ableton pipeline is working, just need to feed it Kinect data

---

## Questions to Consider

1. **Performance Priority**: Do you need full 30fps or is 15-20fps acceptable?
   - Music control typically needs 20fps minimum for responsive interaction
2. **Hand Tracking**: One hand or two-hand tracking?
   - Windows Kinect supports both hands independently
3. **Latency Priority**: Real-time interaction (<100ms) or slight delay ok (200-500ms)?
   - Music performance demands low latency (<100ms ideal)
4. **Visual Feedback Priority**: Do you need the RGB/depth video feed in TD, or just the control data?
   - Syphon for visual feedback adds overhead but looks cool
   - Could skip for pure performance mode
5. **Gesture Complexity**: Simple position XYZ + open/close, or complex gestures (swipe, wave, etc.)?

---

## Recommended Starting Point

Based on analysis, here's the fastest path to a working prototype:

### MVP (Minimum Viable Product) - 4-8 hours work
1. **Adapt `gesture_recognition.py`**:
   - Add OSC sending for hand X, Y, Z, open/close state
   - Test with simple OSC monitor app

2. **TouchDesigner minimal test**:
   - OSC In CHOP receiving hand data
   - MathCHOP to process/smooth values
   - Test mapping to audio parameters (CHOP to Audio)

3. **Once working**:
   - Connect to Ableton via TDAbleton (you already know how)
   - Map hand controls to synth parameters
   - Iterate and refine

### Later Enhancements
- Add Syphon visual feedback (RGB + depth)
- Add more complex gestures
- Add two-hand tracking
- Add point cloud visualization
- Optimize performance

---

---

## Promap: Projection Mapping with Kinect

### Overview
[promap](https://github.com/Wingie/promap) (`~/code/pi-jams/tools/promap/`) is a structured light scanning tool for projection mapping. It computes the geometric relationship between a projector and camera using gray code patterns, producing lookup tables and disparity maps. These feed into [Radiance](https://radiance.video) as `uvmap` and `mask` inputs.

### What We Learned (2026-03-19)

**Pipeline**: `generate → project → capture → decode → invert → reproject`
- Generates 24 gray code patterns for a 1920x1080 projector
- Scanning takes ~1 min (2s per pattern + 5s warmup)
- Produces `lookup.png` (UV map), `disparity.png` (depth), `light.png` (projector's view)

**Reprojection benchmark** (scipy vs cv2.remap):
| Method | Latency | FPS |
|---|---|---|
| scipy (current) | 424 ms | 2.4 |
| cv2.remap | 1.7 ms | 603 |

**Live reproject tested**: confirmed working with webcam + synthetic barrel distortion lookup table. Both scipy and cv2.remap versions verified.

**Zone painting is manual**: promap does NOT auto-segment — you paint zones on `light.png` in GIMP, then feed into Radiance.

### Kinect as Promap Camera

The Kinect v2 can serve as promap's capture device. pylibfreenect2 is confirmed working (import OK, 0 devices since Kinect is in the office).

**Setup required**:
```bash
export DYLD_LIBRARY_PATH=~/code/libfreenect2/build/lib
source ~/code/libfreenect2/venv/bin/activate
```

**Advantages of Kinect over a regular webcam**:
- Built-in depth sensor — could supplement or replace promap's disparity map from gray codes
- Higher quality IR camera — potentially better gray code decoding
- Fixed focus — no autofocus drift during scanning

**Integration path**:
1. Write a thin adapter that wraps pylibfreenect2's RGB capture as an OpenCV-compatible source
2. Pass to promap via `--camera` flag (or modify `capture.py` to accept a freenect2 device)
3. Optionally use Kinect depth data alongside promap's structured light depth for better disparity

### Radiance Workflow
1. `promap -af -v` — scan scene with projector + camera (webcam or Kinect)
2. Open `light.png` in GIMP — paint colored zones to define projection regions
3. Import zone map into Radiance as `uvmap` and `mask`
4. Radiance maps live video/visuals onto the physical object through the projector

### Hardware Needed
- **Projector** — not yet acquired
- **Camera** — webcam works (tested), Kinect v2 available (in office)
- **Radiance** — already running

### Files
```
~/code/pi-jams/tools/promap/
├── benchmark_reproject.py      # scipy vs cv2.remap benchmark
├── live_reproject.py           # live webcam test (scipy, slow)
├── live_reproject_fast.py      # live webcam test (cv2.remap, real-time)
├── learnings.md                # detailed findings
└── promap/                     # main tool
```

---

*Last Updated: 2026-03-19*
*Author: Brainstorming with Claude Code*
*Project: Kinect v2 + TouchDesigner + Ableton Live + Promap on macOS*
