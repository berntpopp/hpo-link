"""Rendered-Compose regression tests for the HPO immutable-data sidecar boundary."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_IMAGE = "ghcr.io/berntpopp/hpo-link@sha256:" + "a" * 64


def _render(*files: str, npm: bool = False) -> dict[str, Any]:
    """Render a Compose model without starting containers."""
    environment = {**os.environ, "HPO_LINK_IMAGE": _IMAGE}
    command = ["docker", "compose"]
    for file in files:
        command.extend(["-f", file])
    if npm:
        command.extend(["--env-file", ".env.docker.example"])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(  # noqa: S603 -- fixed docker-compose argv assembled in this test
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)


def _environment(service: dict[str, Any]) -> dict[str, str]:
    values = service.get("environment", {})
    assert isinstance(values, dict)
    return {str(key): str(value) for key, value in values.items()}


def _mount(service: dict[str, Any], target: str) -> dict[str, Any]:
    mounts = service.get("volumes", [])
    assert isinstance(mounts, list)
    return next(mount for mount in mounts if mount["target"] == target)


def _assert_hardened_init(service: dict[str, Any]) -> None:
    assert service["command"] == ["hpo-link-data", "materialize-data"]
    assert "ports" not in service and "expose" not in service and "healthcheck" not in service
    assert service["restart"] == "no"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["init"] is True
    limits = service["deploy"]["resources"]["limits"]
    assert limits["cpus"] == 1
    assert limits["memory"] == "1073741824"
    assert limits["pids"] == 256
    assert _mount(service, "/data").get("read_only") is not True
    assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=64m,mode=1777"]  # noqa: S108


def _assert_reader(service: dict[str, Any], init_name: str) -> None:
    assert service["depends_on"][init_name]["condition"] == "service_completed_successfully"
    assert _mount(service, "/data")["read_only"] is True
    environment = _environment(service)
    assert environment["HPO_LINK_DATA__DB_FILENAME"] == "current/hpo.sqlite"
    assert environment.get("HPO_LINK_DATA__AUTO_BOOTSTRAP") != "true"
    assert environment.get("HPO_LINK_DATA__REFRESH_ENABLED") != "true"
    assert not any("PREBUILT" in key or "IMMUTABLE_DATA__BUNDLE_URL" in key for key in environment)


def test_production_compose_has_a_hardened_writer_and_read_only_reader() -> None:
    """The sole writer is an init sidecar; the served app waits and reads only."""
    model = _render("docker/docker-compose.yml", "docker/docker-compose.prod.yml")
    init = model["services"]["hpo-data-init"]
    app = model["services"]["hpo-link"]

    _assert_hardened_init(init)
    _assert_reader(app, "hpo-data-init")
    assert init["networks"] == {"default": None}
    assert app["networks"] == {"default": None}
    assert app["image"] == _IMAGE
    assert init["image"] == _IMAGE


def test_npm_compose_has_the_same_init_and_reader_boundary() -> None:
    """The self-contained proxy deployment does not reintroduce app bootstrap."""
    model = _render("docker/docker-compose.npm.yml", npm=True)
    init = model["services"]["hpo-data-init"]
    app = model["services"]["hpo_link"]

    _assert_hardened_init(init)
    _assert_reader(app, "hpo-data-init")
    assert init["networks"] == {"hpo_link_internal_net": None}
    assert set(app["networks"]) == {"hpo_link_internal_net", "npm_proxy_network"}


def test_release_contract_declares_the_immutable_bundle_init_role() -> None:
    """The gate declaration matches the concrete Compose writer boundary."""
    release = json.loads((ROOT / "container-release.json").read_text())

    assert release["data"]["mode"] == "external-reference"
    assert release["smoke"]["profile"] == "immutable-bundle"
    assert release["service"]["auxiliary"] == [
        {
            "name": "hpo-data-init",
            "role": "init",
            "egress": "approved-networks",
            "writable_targets": ["/data", "/tmp"],  # noqa: S108
        }
    ]
