"""Decision 3 of M8-N5-state-review.md, as one pure rule over the pinned catalog.

The sealed model is the newest listed model of the chosen family, at its lowest
listed effort. It is a standing rule, so a pin bump moves it: CI checks the
sealed literals against the catalog CI installed (``tests/test_m8_host_runtime.py``),
and the bump tool reports the same choice for every family.
"""

from __future__ import annotations

import json
import re

EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
"""Efforts ranked by name, never by their order in the catalog. An effort this
ranking does not know might be lower, so it makes the lowest unknowable."""


def catalog_choice(catalog: bytes, family: str) -> tuple[str, str]:
    """The newest listed model of ``family`` and its lowest listed effort.

    "Newest" orders by the numbers in the slug (``gpt-6.1-sol`` after
    ``gpt-6-sol``). A family with no listed model, or a model listing an
    effort outside :data:`EFFORTS`, refuses rather than guessing.
    """

    models = [
        model for model in json.loads(catalog)["models"]
        if model.get("visibility") == "list" and model["slug"].endswith(f"-{family}")
    ]
    if not models:
        raise ValueError(f"the catalog lists no {family!r} model")
    newest = max(models, key=lambda model: [int(n) for n in re.findall(r"\d+", model["slug"])])
    efforts = {level["effort"] for level in newest.get("supported_reasoning_levels", [])}
    if not efforts or not efforts <= set(EFFORTS):
        raise ValueError(f"{newest['slug']!r} lists no ranked lowest effort")
    return newest["slug"], min(efforts, key=EFFORTS.index)
