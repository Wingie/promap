#!/usr/bin/env python3
"""CLI wrapper for SAM-based auto-segmentation of promap zones."""

from tools.promap.segment.segment import main

if __name__ == "__main__":
    exit(main() or 0)
