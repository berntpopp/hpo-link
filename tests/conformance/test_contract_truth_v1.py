"""Contract Truth v1 gate against the live HPO MCP registry."""

from __future__ import annotations

import asyncio
import socket
from hashlib import sha256
from pathlib import Path
from typing import NoReturn

import pytest

EXPECTED_HELPER_SHA256 = "e6c12b087c8231f5324c6388abd01afaeffa305a84d0b7c0e3629e17993d3674"


async def test_documentation_matches_live_mcp_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Lint repository documentation against the production MCP registry."""
    helper_path = Path(__file__).with_name("contract_truth.py")
    pin_path = Path(__file__).with_name("contract_truth.sha256")

    vendored_pin = pin_path.read_text(encoding="utf-8").strip()
    assert vendored_pin == EXPECTED_HELPER_SHA256
    assert sha256(helper_path.read_bytes()).hexdigest() == vendored_pin

    def reject_socket(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("contract-truth registry discovery attempted network access")

    async def reject_asyncio(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("contract-truth registry discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", reject_socket)
    monkeypatch.setattr(asyncio, "open_connection", reject_asyncio)
    monkeypatch.setenv("HPO_LINK_DATA__DATA_DIR", str(tmp_path / "must-not-be-read"))
    monkeypatch.setenv("HPO_LINK_DATA__AUTO_BOOTSTRAP", "false")
    monkeypatch.chdir(tmp_path)

    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.mcp.service_adapters import (
        reset_services,
        set_annotation_service,
        set_hpo_service,
    )
    from hpo_link.services.annotation_service import AnnotationService
    from hpo_link.services.hpo_service import HpoService

    from .contract_truth import (
        active_markdown_files,
        historical_markdown_files,
        lint_repository,
    )

    set_hpo_service(HpoService(None))
    set_annotation_service(AnnotationService(None))
    try:
        tools = await create_hpo_mcp().list_tools()
    finally:
        reset_services()

    assert tools, "the live MCP registry must not be empty"
    catalog: dict[str, dict[str, object]] = {}
    for tool in tools:
        assert isinstance(tool.parameters, dict)
        catalog[tool.name] = {"inputSchema": tool.parameters}

    repo_root = Path(__file__).resolve().parents[2]
    assert active_markdown_files(repo_root), "active Markdown discovery must not be empty"
    assert historical_markdown_files(repo_root), "historical Markdown discovery must not be empty"

    findings = lint_repository(repo_root, catalog)
    rendered = "\n".join(
        f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in findings
    )
    assert not findings, rendered
