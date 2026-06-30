"""Security guard: the base docker-compose must not publish the unauthenticated
backend on all interfaces (0.0.0.0). It is dev/local-only and must loopback-bind
the host port; production reaches the backend only via the router/reverse proxy.
Research use only; not clinical decision support."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_base_compose_binds_published_ports_to_loopback() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    published = [
        (name, mapping)
        for name, svc in compose["services"].items()
        for mapping in (svc.get("ports") or [])
    ]
    assert published, "base compose should publish at least one host port for local/dev use"
    for name, mapping in published:
        assert isinstance(mapping, str), (
            f"{name} uses long-form ports; extend this guard to read host_ip"
        )
        assert mapping.startswith("127.0.0.1:"), (
            f"{name} publishes {mapping!r} on all interfaces; bind the "
            "unauthenticated backend to loopback (127.0.0.1) — Docker otherwise "
            "binds 0.0.0.0 and bypasses the host firewall. Production reaches it "
            "only via the router/reverse proxy."
        )
