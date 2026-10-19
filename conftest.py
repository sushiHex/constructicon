"""Refuse foreign development sources before importing the test fixtures."""

from importlib.util import find_spec
from pathlib import Path

import pytest

_expected = Path(__file__).resolve().parent / "src" / "constructicon" / "__init__.py"
_spec = find_spec("constructicon")
_actual = Path(_spec.origin).resolve() if _spec is not None and _spec.origin else None
if _actual != _expected.resolve():
    raise pytest.UsageError(
        "constructicon source mismatch: "
        f"expected {_expected}; resolved {_actual if _actual is not None else 'missing'}. "
        "From this checkout, use its own environment: uv run --no-active verify. "
        "Remove a foreign UV_PROJECT_ENVIRONMENT or PYTHONPATH override first."
    )
