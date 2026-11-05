"""Compatibility import for the installed fixed M9 evidence."""

import sys

from constructicon.api._m9 import evidence as _implementation

sys.modules[__name__] = _implementation
