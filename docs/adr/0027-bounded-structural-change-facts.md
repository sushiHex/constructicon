# 0027 — Bounded structural facts for change-review advice

Decision status is recorded in the [ADR index](README.md), for
[#453](https://github.com/sushiHex/constructicon/issues/453). Acceptance of this
exact artifact authorizes credential-free construction only; it authorizes no
live window, installation, standing record, credential or model call.
Source references are to main at `568a76a` unless stated otherwise.

## Context

The accepted generation-23 delivery returned the exact advice and metering to
its requester. Delivery is established; the usefulness of the advice is limited
by its input. `examples/change_review.py::compare_sources` reports top-level
public function/class names and counts. The route's closed `ChangeSummaryV1`
also carries source hashes, syntax status and partial reporting.

Actual producer calls establish these limits:

| Paired change | V1 observation | Question V1 cannot answer |
| --- | --- | --- |
| Public function body versus parameter change | Both list the same changed name | Did the definition header change? |
| Private function body only | Different source hashes, no public symbol changes | Did the parsed module change, or only ignored text? |
| Imports reordered against module statements | Different hashes, no public symbol changes | Is the parsed module AST unchanged? |
| Public definitions reordered | Different hashes, no public symbol changes | Is the parsed module AST unchanged? |

These are information gaps, not false results: V1 states its public-symbol scope.
They do not establish that a model given more facts will produce better advice.

## Proposed decision

Supersede only ADR 0025 section 3's closed instruction-summary field list for
the new advice component version. Retain its source/path exclusions, one-node
graph, instruction-bound run identity and opaque advisory reply. ADRs 0024 and
0026 continue governing metering and standing approval without amendment.

Keep the V1 base field names, with the V2 scope literal
`top-level public definition parts and whole-module AST comparison only`,
and add three required fields to `ChangeSummaryV2`:

| Field | Closed value |
| --- | --- |
| `kinds` | Fixed `added`/`removed`/`changed` lists aligned by position with the respective symbol lists, or null. Values are `function`, `async_function`, `class` and `multiple`. |
| `changed_parts` | List aligned by position with `symbols.changed`, or null. Each entry is a unique sorted subset of `kind`, `signature`, `decorators`, `docstring` and `body`. A duplicate-definition group has null instead of a part list. |
| `module_ast_changed` | Boolean comparing the complete parsed ASTs, or null when comparison is unavailable. |

No new authored identifier text is added or repeated in the new fields. The
existing symbol lists are the names; metadata uses their checked ordinal alignment.
These are syntactic observations, never a claim of compatibility, safety,
coverage, behavioral correctness or test execution.

### Exact meaning

- A name's kind is its after-definition kind, or its before-kind when removed.
  If either relevant snapshot contains multiple definitions for that name,
  report `multiple`. Do not guess one binding or align duplicate definitions.
- For one definition on each side, `signature` compares all AST fields other
  than name, body and decorators: function arguments/returns/type parameters,
  or class bases/keywords/type parameters. A function/class transition reports
  signature changed because those field sets differ. A sync/async transition
  alone reports kind changed, not a header change. None proves an API break.
- `decorators` compares the decorator AST list. `docstring` compares the
  leading string Expr node's AST, including literal prefix/kind;
  `body` compares the remaining statements. `kind` records a function/async-function/class transition.
- A class body is one body. Its flag does not identify a method or establish
  member coverage. No method inventory is added.
- `module_ast_changed` compares the complete ordered AST representation, with
  location attributes excluded. It observes order changes across statement
  categories and public definitions; grouped category comparisons cannot
  establish AST equality. Comments/whitespace ignored by the parser are not
  structural changes.

Use the existing bounded local source preflight and parser. Source text and
AST dumps remain local; no source, diff, default expression, annotation text,
decorator expression, diagnostic excerpt, GitRef or path enters the instruction.

### Bounds and unknowns

Retain the existing 32,768-byte source bound, at most 25 names per change list,
80-character displayed identifiers, named syntax failures and partial reporting.
When comparison is unavailable, all three new fields are null. When names are
partial, `kinds` and `changed_parts` are null; the whole-module boolean
remains known when parsing/comparison completed. Never treat missing detail as
a negative fact or copy it onto colliding identifier prefixes.

When complete, kinds has exactly the three change-list keys, and every kind
list has exactly its symbol list's length. The changed-parts list has exactly
the changed-symbol list's length. For changed names, kind is multiple exactly
when the corresponding parts entry is null. Other changed names have a nonempty unique sorted list of measured parts.
Invalid keys, lengths or combinations refuse; they are never repaired or filled
with guessed values.

The canonical instruction remains LF-only UTF-8, at most 8,192 bytes. Additional
metadata makes some V1-admissible inputs exceed that ceiling: refuse the
instruction by name, never silently drop fields to make it fit. A producer-grounded
boundary pair (5,800/5,900 source bytes, 25 names in each bucket, 80 characters per
name) measures 6,985 instruction bytes for V1, 17,939 for name-keyed metadata and
9,673 for aligned metadata under the unchanged V1 framing. This motivates aligned
lists but does not eliminate the refusal regression.

The fixed V2 framing changes to explain the ordinal alignment, explicit nulls
and syntactic scope. It adds bytes, so implementation must measure its actual
instruction at the binding boundary; the numbers above are comparative prototype
measurements, not final V2 sizes. Reply remains at most 16,384 bytes. Metering
and its unknown monetary fields are copied unchanged.

## Identity, history and authorization

Build advice facts in a separate local `compare_advice_sources` function,
composed by the optional advice entry and `change_review_input.prepare`.
Do not widen `compare_sources`, `ChangeSummary`, `ReviewInput` or the human
graph's port schemas. Source preflight stays local; no new executor primitive
or generic AST protocol is introduced.

Use the existing route, nominal summary port, graph shape and fixed actor.
The changed schema and whole-module guard rotate component and source-graph
identities. Use a new `change-review-advice-v2:` instruction key prefix.
Keep the default human-review graph and its exact contract goldens unchanged.

The new active advice route requires V2. Do not silently upgrade V1 packets or
invent historical fields. Retained V1 packets/journals remain associated with
their original pinned tooling and controller; current reply collection must
not reinterpret them under new component pins. No history migration or dual
active route is introduced.

The existing standing record does not fit the new controller/component/guard.
Construction is credential-free. Any later installation, successor record and
fresh qualification/model dispatch require their own concrete selected scope.
No live window is a gate merely to reconfirm unchanged containment or delivery.
The executor remains generally unavailable; no credential, API-key, provider,
grant, transport, permit, closure or availability change is proposed.

## Alternatives and evidence limits

- Retain V1 and narrow the product claim: cheapest, but leaves the specific
  information gaps above.
- Kind only: identifies a symbol category without distinguishing header/body
  changes or module changes outside the tracked symbol set.
- Add member names or source/diffs: more data and complexity without a need
  established by this wave; source/diffs remain excluded.
- Categorize outside statements and infer whole-module equality from empty
  category changes: loses cross-category ordering. The exact module boolean
  avoids that inference with one bounded fact.

The selected verification is accepting/refusing producer-grounded fixtures,
whole-chain credential-free preparation/dispatch/reply/teardown, closed fields,
ambiguity/partial/byte bounds and preserved human-graph identities. An independent
review checks the data/identity boundary; final code CI runs once on the coherent
candidate. A model-quality gain remains unmeasured without a separately selected
evaluation; deterministic information sufficiency must not be reported as one.
