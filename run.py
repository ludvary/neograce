#!/usr/bin/env python3
"""Convenience launcher:  python run.py [files...]"""
import sys

from neograce.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
