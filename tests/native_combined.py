"""Assertions for one controlled native recipe, not a production request filter.

The tool golden is from the previously reviewed pinned-binary artifact, not the
request under test. Context is constructed independently from the controller's
recipe. Only message IDs and the bounded invocation date may vary. This checks
bytes/shape, never process authorship; a descendant can reproduce them.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from tests.native_codex_probe import PROBE_PROMPT
from tests.native_startup import MODELS, configuration

BASE_INSTRUCTIONS = "Execute only the deterministic offline test scenario."
PERMISSIONS = (
    "<permissions instructions>\n"
    "Filesystem sandboxing defines which files can be read or written. "
    "`sandbox_mode` is `danger-full-access`: No filesystem sandboxing - all commands "
    "are permitted. Network access is enabled.\n"
    "Approval policy is currently never. Do not provide the `sandbox_permissions` "
    "for any reason, commands will be rejected.\n</permissions instructions>"
)


def controlled_configuration(model, *, images=False):
    return configuration(model).replace(
        "view_image = false", f"view_image = {str(images).lower()}",
    ) + "\n[skills]\ninclude_instructions = false\n[skills.bundled]\nenabled = false\n"


def environment(date):
    return (
        "<environment_context>\n  <cwd>/tmp/native-startup</cwd>\n  <shell>sh</shell>\n"
        f"  <current_date>{date}</current_date>\n  <timezone>Etc/UTC</timezone>\n"
        "  <filesystem><workspace_roots><root>/tmp/native-startup</root></workspace_roots>"
        '<permission_profile type="disabled"><file_system type="unrestricted" />'
        "</permission_profile></filesystem>\n</environment_context>"
    )


def message(role, *texts):
    return {"type": "message", "role": role,
            "content": [{"type": "input_text", "text": text} for text in texts]}


def tools_for(*, images=False, restricted=True):
    golden = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "native_combined_tools.json",
    ).read_text())
    return [tool for tool in golden if not (
        (tool["name"] == "view_image" and not images)
        or (tool["name"] == "apply_patch" and restricted)
    )]


def without_ids(items):
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
        for item in items
    ):
        raise ValueError("missing native item identity")
    return [{key: value for key, value in item.items() if key != "id"} for item in items]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CombinedScenario:
    model: str
    dates: tuple[str, ...]
    tool: str
    arguments: dict
    output: object
    images: bool = False
    restricted: bool = True

    def prefix(self, date):
        prefix = []
        if self.model == MODELS[1]:
            prefix = [{"type": "additional_tools", "role": "developer", "tools": [{
                "type": "namespace", "name": "functions", "description": "",
                "tools": tools_for(images=self.images, restricted=self.restricted),
            }]}, message("developer", BASE_INSTRUCTIONS)]
        return [*prefix, message("developer", PERMISSIONS), message("user", environment(date)),
                message("user", PROBE_PROMPT)]

    def suffix(self):
        call = {"call_id": "call_probe", "name": self.tool}
        if self.tool == "apply_patch":
            call.update(type="custom_tool_call", input=self.arguments["patch"])
            kind = "custom_tool_call_output"
        else:
            call.update(type="function_call", arguments=json.dumps(self.arguments))
            kind = "function_call_output"
        return [call, {"type": kind, "call_id": "call_probe", "output": self.output}]

    def __call__(self, request, ordinal):
        if self.model not in MODELS or request.get("model") != self.model or ordinal not in (1, 2):
            raise ValueError("unexpected combined model or request ordinal")
        if self.model == MODELS[0]:
            if request.get("instructions") != BASE_INSTRUCTIONS or canonical(
                request.get("tools"),
            ) != canonical(tools_for(images=self.images, restricted=self.restricted)):
                raise ValueError("changed native instructions or tools")
        elif "instructions" in request or "tools" in request:
            raise ValueError("flattened namespaced model request")
        actual = without_ids(request.get("input"))
        suffix = self.suffix() if ordinal == 2 else []
        if not any(canonical(actual) == canonical(self.prefix(date) + suffix)
                   for date in self.dates):
            raise ValueError("unexpected native context or conversation")
