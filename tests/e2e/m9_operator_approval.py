"""Compatibility import for the installed fixed M9 approval."""

import sys

from constructicon.api._m9 import approval as _implementation

sys.modules[__name__] = _implementation
