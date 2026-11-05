"""Compatibility import for the installed fixed M9 fixture."""

import sys

from constructicon.api._m9 import fixture as _implementation

sys.modules[__name__] = _implementation
