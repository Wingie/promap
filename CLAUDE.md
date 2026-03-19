# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is promap

`promap` is a CLI tool for projection mapping. It uses a projector and camera to compute the physical scene as viewed from the projector, producing lookup tables and disparity (depth) maps via gray code structured light scanning.

## Install & Run

```bash
pip install -e .                  # editable install (numpy, scipy required; opencv used at runtime)
promap -af -v                     # run full pipeline with all files + verbose
python -m promap                  # alternative invocation
```

There are no tests in this project.

## Pipeline Architecture

The pipeline is a linear 6-stage process where operations must be **contiguous** (you can't skip a middle step):

```
generate → project → capture → decode → invert → reproject
  (-g)      (-p)      (-c)      (-d)     (-i)      (-r)
```

Each stage can load/save intermediate files, so you can run subsets (e.g. `-gpc` for scanning, `-dir` for analysis). The `-a` flag runs all stages; `-f` saves all intermediates.

**Key code flow:** `__init__.py` contains `main()` with the argparser and all `op_*` functions that orchestrate the pipeline. Each stage imports its module lazily. State flows between stages via `args` attributes (`gray_code_images`, `captured_images`, `decoded_image`, `lookup_image`).

## Module Responsibilities

| Module | Purpose |
|---|---|
| `__init__.py` | CLI entry point, argument parsing, pipeline orchestration, file I/O helpers |
| `gray.py` | Gray code pattern generation |
| `project.py` | Fullscreen projection of patterns (uses display/screen APIs) |
| `capture.py` | Camera capture (uses OpenCV VideoCapture) |
| `decode.py` | Threshold + decode gray code images → camera-to-projector lookup |
| `reproject.py` | Invert lookup table (least-squares), compute disparity, reproject images |

## Key Conventions

- Image coordinates stored as `(width, height)` tuples but numpy arrays are `(height, width)`
- Lookup/decoded images encode X in blue channel, Y in green channel (BGR format via OpenCV)
- Normalized mode (default): UV coordinates stored as uint16 floats via `float_to_int`/`int_to_float`
- File naming uses `filename2format()` to insert zero-padded indices before the extension (e.g. `cap.png` → `cap000.png`)
- OpenCV (`cv2`) is used for all image I/O but is not listed in `install_requires` (removed as pip dependency due to install issues)
