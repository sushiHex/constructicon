# ADR 0008 — Isolation is admission logic; grants compile

**Decision.** Executors declare an `IsolationProfile`; admission rejects a live
execution whose executor cannot mechanically satisfy the requested posture —
never "best effort READ". Fake runs everywhere; Codex where its OS sandbox
satisfies the contract; Claude Code strict-READ requires a substrate-owned
sandbox wrapper; an unsandboxed shell-capable executor is unavailable for that
posture. Backend flags remain defense in depth (measured upstream: tool
denylists are a command classifier, not containment).

Authored `GrantRequest`s may inherit; the manifest carries only fully concrete
`EffectiveGrants` — `None`/"inherit" do not survive admission, root
inheritance is a fault, and grants only narrow along the composition chain.
