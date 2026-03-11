"""Shared pytest configuration."""

import sys
import os

# Ensure backend/ is on the path for all test modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
