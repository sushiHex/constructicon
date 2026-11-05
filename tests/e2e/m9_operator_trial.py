"""Compatibility import for the installed fixed M9 trial."""

import sys

from constructicon.api._m9 import trial as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
