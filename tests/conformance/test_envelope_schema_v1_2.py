"""Response-Envelope v1.2: every data tool's result validates against the published schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0
(``envelope-v1.2.schema.json``); its digest is pinned in the sibling ``.sha256`` file.
Each tool is called in-process on the fixture index with the ``examples`` of its own
input schema.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from hpo_link.mcp.capabilities import TOOLS
from hpo_link.mcp.service_adapters import reset_services, set_annotation_service, set_hpo_service

_HERE = Path(__file__).parent
_SCHEMA_FILE = _HERE / "envelope-v1.2.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_FILE.read_text(encoding="utf-8")))

_OPS_TOOLS = {"get_server_capabilities", "get_diagnostics"}  # outside the v1.2 rule
_DATA_TOOLS = sorted(set(TOOLS) - _OPS_TOOLS)
_PROVENANCE = ("source", "data_version", "retrieved_at")

#: Arguments where the schema example is not in the fixture index.
_OVERRIDES: dict[str, dict[str, Any]] = {
    "score_genes_for_phenotypes": {"hpo_ids": ["HP:0000479"]},
    "get_genes_for_phenotype": {"hpo_id": "HP:0000479"},
    "get_diseases_for_phenotype": {"hpo_id": "HP:0000479"},
}


@pytest.fixture()
def mcp(built_test_db: Path) -> Iterator[Any]:
    """The real server over the fixture index."""
    from hpo_link.data.repository import HpoRepository
    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.services.annotation_service import AnnotationService
    from hpo_link.services.hpo_service import HpoService

    reset_services()
    repo = HpoRepository(built_test_db)
    set_hpo_service(HpoService(repo))
    set_annotation_service(AnnotationService(repo))
    yield create_hpo_mcp()
    repo.close()
    reset_services()


async def _call(mcp: Any, name: str, **extra: Any) -> Any:
    if name in _OVERRIDES:
        arguments = dict(_OVERRIDES[name])
    else:
        schema = next(t for t in await mcp.list_tools() if t.name == name).parameters
        arguments = {p: schema["properties"][p]["examples"][0] for p in schema.get("required", [])}
    return await mcp.call_tool(name, {**arguments, **extra})


def _violations(envelope: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in _VALIDATOR.iter_errors(envelope)
    ]


def test_vendored_schema_is_the_pinned_release() -> None:
    pin = (_HERE / "envelope-v1.2.schema.sha256").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(_SCHEMA_FILE.read_bytes()).hexdigest() == pin


@pytest.mark.parametrize("mode", ["minimal", "compact", "full"])
@pytest.mark.parametrize("tool", _DATA_TOOLS)
async def test_data_tool_result_validates(mcp: Any, tool: str, mode: str) -> None:
    result = await _call(mcp, tool, response_mode=mode)
    envelope = result.structured_content
    assert envelope["success"] is True
    assert _violations(envelope) == []
    mirrored = json.loads(result.content[0].text)["_meta"]  # the text block mirrors _meta
    for field in _PROVENANCE:
        assert isinstance(envelope["_meta"][field], str) and envelope["_meta"][field], field
        assert mirrored[field] == envelope["_meta"][field]


async def test_provenance_names_the_hpo_release_and_its_download(
    mcp: Any, built_test_db: Path
) -> None:
    from hpo_link.data.repository import HpoRepository

    repo = HpoRepository(built_test_db)
    built = repo.read_meta()
    repo.close()
    envelope = (await _call(mcp, "get_term")).structured_content
    meta = envelope["_meta"]
    assert meta["source"] == "hpo"
    assert meta["data_version"] == built["hpo_version"] == envelope["hpo_version"]
    assert meta["retrieved_at"] == built["build_utc"][:19] + "Z"


async def test_error_results_validate(mcp: Any) -> None:
    calls = [
        ("get_term", {"hpo_id": "HP:9999999"}),  # not_found
        ("get_term", {"hpo_id": "HP:0000118", "bogus": 1}),  # argument binding
        ("get_term", {"hpo_id": "not-an-id"}),  # invalid_input
        ("no_such_tool", {}),  # unknown tool
    ]
    for tool, arguments in calls:
        for mode in ("minimal", "compact"):
            if tool != "no_such_tool":
                arguments = {**arguments, "response_mode": mode}
            result = await mcp.call_tool(tool, arguments)
            assert result.structured_content["success"] is False
            assert list(_VALIDATOR.iter_errors(result.structured_content)) == []
