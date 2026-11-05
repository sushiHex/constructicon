"""Compatibility import for the installed fixed M9 evaluator."""

import sys

from constructicon.api._m9 import evaluator as _implementation

sys.modules[__name__] = _implementation
