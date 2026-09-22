"""Load tests/_sandbox.py by path so it applies under any pytest import mode."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("_sandbox.py")))
