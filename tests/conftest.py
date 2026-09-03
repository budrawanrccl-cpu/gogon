import os
import sys

# Ensure the repo root (containing the `bot` package) is importable regardless
# of how pytest is invoked.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
