"""The fake outside world — independently durable, so recovery tests prove
their claims against a second store the runtime cannot see."""

from constructicon.substrate.external.fake import FakeExternalLedger

__all__ = ["FakeExternalLedger"]
