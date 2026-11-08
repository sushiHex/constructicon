"""One trusted exact-extraction exam for the channel stored-reply helper.

Standard library only: the contained gate embeds this whole source and never
imports the base, the candidate or any project module. Both syntax trees are
built from **raw bytes** in the same interpreter, so an encoding declaration
is resolved exactly as Python's loader resolves it. Acceptance proves this one
closed rewrite of the pinned base, not general semantic equivalence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import sys

CHECK_NAME = "channel-stored-reply-exact-extraction"
TARGET_PATH = "src/constructicon/substrate/channels/in_process.py"
MAX_SOURCE_BYTES = 65536
CLASS_NAME = "InProcessChannel"
HELPER_NAME = "_stored_reply"
# The helper's fixed position: immediately after this method of the class.
HELPER_AFTER = "_complete_message"
CALLERS = ("reply_for", "acknowledge")

# The three statements both callers repeat, spelled with each caller's own
# identifier and result name. The fault text keeps the caller's identifier.
_BLOCK = (
    "if request.reply_port is None:\n"
    '    raise JournalDamaged(f"channel request {{{identifier}}} pins no reply port")\n'
    "reply_id = reply_message_id(\n"
    "    request_id=request.message_id,\n"
    "    reply_port=request.reply_port,\n"
    ")\n"
    "{result} = self._by_id.get(str(reply_id))\n"
)
_CALL = "{result} = self._stored_reply(request, {identifier})\n"
_CALLER_NAMES = {"reply_for": ("request_id", "stored"), "acknowledge": ("message_id", "reply")}
HELPER_SOURCE = (
    "def _stored_reply(\n"
    "    self,\n"
    "    request: ChannelMessage,\n"
    "    request_id: Digest,\n"
    ") -> ChannelMessage | None:\n"
    "    if request.reply_port is None:\n"
    '        raise JournalDamaged(f"channel request {request_id} pins no reply port")\n'
    "    reply_id = reply_message_id(\n"
    "        request_id=request.message_id,\n"
    "        reply_port=request.reply_port,\n"
    "    )\n"
    "    return self._by_id.get(str(reply_id))\n"
)


class ExtractionRefusal(ValueError):
    """A closed reason code; never candidate-controlled diagnostic text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def parse_source(raw: bytes, role: str) -> ast.Module:
    """Bounded raw-bytes parse; a decoded ``str`` would bypass the loader's cookie."""
    if type(raw) is not bytes:
        raise ExtractionRefusal(f"{role}-not-bytes")
    if len(raw) > MAX_SOURCE_BYTES:
        raise ExtractionRefusal(f"{role}-too-large")
    try:
        return ast.parse(raw, filename=f"<{role}>", mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise ExtractionRefusal(f"{role}-unparsable") from None


def _statements(source: str) -> list[str]:
    return [_dump(statement) for statement in ast.parse(source).body]


def _method(module: ast.Module, name: str) -> ast.FunctionDef:
    classes = [node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME]
    if len(classes) != 1:
        raise ExtractionRefusal("base-class-missing")
    methods = [node for node in classes[0].body
               if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(methods) != 1:
        raise ExtractionRefusal("base-method-missing")
    return methods[0]


def _replace_block(method: ast.FunctionDef, identifier: str, result: str) -> None:
    block = _statements(_BLOCK.format(identifier=identifier, result=result))
    call = ast.parse(_CALL.format(identifier=identifier, result=result)).body
    sites = []
    for node in ast.walk(method):
        for _, value in ast.iter_fields(node):
            if not (isinstance(value, list) and value
                    and all(isinstance(item, ast.stmt) for item in value)):
                continue
            dumps = [_dump(item) for item in value]
            for index in range(len(dumps) - len(block) + 1):
                if dumps[index:index + len(block)] == block:
                    sites.append((value, index))
    if len(sites) != 1:
        raise ExtractionRefusal("base-block-missing")
    statements, index = sites[0]
    statements[index:index + len(block)] = call


def expected_module(base: bytes) -> ast.Module:
    """The one closed rewrite of the pinned base; refuses a base it cannot apply to."""
    module = parse_source(base, "base")
    for node in ast.walk(module):
        if (
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
             and node.name == HELPER_NAME)
            or (isinstance(node, ast.Attribute) and node.attr == HELPER_NAME)
            or (isinstance(node, ast.Name) and node.id == HELPER_NAME)
        ):
            raise ExtractionRefusal("base-has-helper")
    expected = copy.deepcopy(module)
    for name in CALLERS:
        identifier, result = _CALLER_NAMES[name]
        _replace_block(_method(expected, name), identifier, result)
    owner = next(node for node in expected.body
                 if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME)
    anchors = [index for index, node in enumerate(owner.body)
               if isinstance(node, ast.FunctionDef) and node.name == HELPER_AFTER]
    if len(anchors) != 1:
        raise ExtractionRefusal("base-anchor-missing")
    owner.body.insert(anchors[0] + 1, ast.parse(HELPER_SOURCE).body[0])
    return expected


def check_extraction(base: bytes, candidate: bytes) -> dict[str, object]:
    """Accept only a whole-module tree equal to the expected extraction."""
    expected = _dump(expected_module(base))
    observed = _dump(parse_source(candidate, "candidate"))
    if observed != expected:
        raise ExtractionRefusal("candidate-differs")
    return {
        "passed": True,
        "check": CHECK_NAME,
        "python": sys.version,
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
    }
