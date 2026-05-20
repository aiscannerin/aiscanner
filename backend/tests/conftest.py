"""
conftest.py — pytest session-level setup for the backend test suite.

IMPORTANT: Imports here run before any test module is collected.
This ensures that real library modules (flask, flask_sqlalchemy, sqlalchemy)
are registered in sys.modules BEFORE other test files call _stub(name) on them.
test_nse_fetch_layer.py uses _stub() which does `if name not in sys.modules`
so pre-importing here means the stub is silently skipped for real packages.
"""

# Pre-import real packages so _stub() in other test files skips them.
# Order matters: flask must be registered before test_nse_fetch_layer.py
# collection runs the module-level _stub("flask") call.
import flask           # noqa: F401  — registers sys.modules["flask"]
import flask_sqlalchemy # noqa: F401  — registers sys.modules["flask_sqlalchemy"]
import sqlalchemy       # noqa: F401  — registers sys.modules["sqlalchemy"]
