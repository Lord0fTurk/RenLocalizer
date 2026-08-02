# -*- coding: utf-8 -*-
"""
Pytest global configuration and fixtures.
Ensures deterministic, headless Qt environment execution across CI and local runners.
"""

import os
import sys

# Force Qt offscreen platform plugin in headless environments if not already specified
if "QT_QPA_PLATFORM" not in os.environ and sys.platform != "win32":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
