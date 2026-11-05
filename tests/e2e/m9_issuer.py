"""Compatibility import for the installed fixed M9 issuer."""

import sys

from constructicon.api._m9 import issuer as _implementation

sys.modules[__name__] = _implementation
