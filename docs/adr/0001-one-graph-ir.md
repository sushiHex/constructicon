# ADR 0001 — One graph IR, one admission boundary

**Decision.** SDK combinators, hand-authored JSON, and architect-proposed
graphs all compile to the same `Graph` (three constructs: Ref, Graph, Loop)
and pass one validator. Deliberately supersedes an earlier position that
workflows are arbitrary async Python: a graph IR removes any determinism
constraint on user code (there is no user code between nodes), makes resume a
re-walk, and gives dynamic (architect-proposed) structure the same admission
path as authored structure — LLMs propose topology, code disposes.

**Rejected.** A separate textual DSL (the JSON form of the IR is the
serialization); a second workflow representation; privileged IR constructs for
panels/gates/learning (they are registered components).
