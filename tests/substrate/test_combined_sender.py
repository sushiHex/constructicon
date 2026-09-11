"""A matching transcript proves invocation receipt, not native authorship."""

import json

import pytest

from tests.native_codex_probe import PROBE_PROMPT
from tests.native_combined import CombinedScenario
from tests.native_startup import MODELS
from tests.substrate._provider_transport import ENDPOINT
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement
from tests.substrate.test_provider_placement import placement_image as placement_image
from tests.test_native_combined import request_for
from tests.test_native_provider import request_bytes


@pytest.mark.parametrize("model", MODELS)
async def test_contained_descendant_can_reproduce_a_permitted_transcript(
    placement_image, tmp_path, model,
):
    scenario = CombinedScenario(model, ("2026-09-11",), "contained_python",
                                {"program": "inert"}, "invented tool output")
    requests = [request_bytes(request_for(scenario, ordinal)).hex() for ordinal in (1, 2)]
    child = (
        "import json,os,socket,sys\n"
        f"requests={requests!r}\n"
        "observed=[]\n"
        "for ordinal,raw in enumerate(requests):\n"
        " family=socket.AF_INET if ordinal==0 else socket.AF_UNIX\n"
        f" address=('127.0.0.1',int(sys.argv[1])) if ordinal==0 else {ENDPOINT!r}\n"
        " with socket.socket(family) as sock:\n"
        "  sock.settimeout(5); sock.connect(address)\n"
        "  sock.sendall(bytes.fromhex(raw)); sock.shutdown(socket.SHUT_WR)\n"
        "  response=bytearray()\n"
        "  while chunk:=sock.recv(8192):\n"
        "   response.extend(chunk)\n"
        "   assert len(response)<1048576\n"
        "  assert response.startswith(b'HTTP/1.1 200 OK')\n"
        "  observed.append({'path':'loopback' if ordinal==0 else 'direct-socket',"
        "'response':response.hex()})\n"
        "print(json.dumps({'sender':'non-native-child','pid':os.getpid(),"
        "'observations':observed}),flush=True)\n"
    )
    probe = (
        "import subprocess,sys\n"
        f"result=subprocess.run(['/usr/bin/python3','-I','-c',{child!r},sys.argv[1]],timeout=12)\n"
        "raise SystemExit(result.returncode)\n"
    )
    async with placement(placement_image, model=model, scenario=PROBE_PROMPT, tool=scenario.tool,
                         arguments=scenario.arguments, request_check=scenario) as fixture:
        composed, peer, record = fixture
        record["sender_control"] = {"native": False, "model_label": model}
        observations, result = await observe(composed, peer, tmp_path, probe=probe, record=record)
    assert_outcome(result)
    assert len(peer.requests) == 2 and not peer.failures
    for ordinal, request in enumerate(peer.requests, 1):
        scenario(request, ordinal)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    sender = [row for row in records if row.get("sender") == "non-native-child"]
    assert len(sender) == 1
    assert [row["path"] for row in sender[0]["observations"]] == ["loopback", "direct-socket"]
    assert observations["sender_control"]["native"] is False
