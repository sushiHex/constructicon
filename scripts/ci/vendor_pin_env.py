"""Print the workflow's vendor pin as shell assignments, for CI's signature check only.

Every value has already matched its strict pattern in ``vendor_pin``, so none
can carry a quote, a space or a newline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m8_host_artifacts import WORKFLOW, vendor_pin

checkout = (Path(__file__).resolve().parents[2] / WORKFLOW).read_bytes()
pin = vendor_pin(checkout.replace(b"\r\n", b"\n"))
for key in ("codex_url", "version", "catalog_commit"):
    print(f"CODEX_PIN_{key.upper()}={pin[key]}")
