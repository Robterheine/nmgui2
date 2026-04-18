#!/usr/bin/env python3
"""
NMGUI v2 — Compatibility shim.

The application now lives in the nmgui2/ package.
Run with:  python3 nmgui2.py          (this file)
       or: python3 -m nmgui2          (package entry point)
"""
import sys
from nmgui2.__main__ import main

if __name__ == '__main__':
    main()
