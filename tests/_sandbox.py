"""Run the suite against a throwaway home, never the caller's real vault.

Harness modules read AGENT_HARNESS_*/MAM_* at import or call time, and where a
variable is missing they fall back to `Path.home()/'.agent-harness'` (see
execution/context_budget.py, execution/index_workers.py, mam.py). So dropping
the variables alone would aim the suite at the real vault instead of away from
it: the home has to move too. Subprocesses inherit both.

unittest never loads conftest.py, so `tests/__init__.py` imports this module
directly to make sure the sandbox is set up under `python -m unittest` too.
"""
import atexit
import os
import shutil
import tempfile

_SANDBOX = os.environ.get("HARNESS_TEST_SANDBOX")

if not _SANDBOX or not os.path.isdir(_SANDBOX):
    _SANDBOX = tempfile.mkdtemp(prefix="agent-harness-tests-")
    atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)

    for _key in [k for k in os.environ if k.startswith(("AGENT_HARNESS_", "MAM_"))]:
        del os.environ[_key]
    os.environ["HOME"] = os.environ["USERPROFILE"] = _SANDBOX  # Path.home(), both platforms
    os.environ["HARNESS_TEST_SANDBOX"] = _SANDBOX
