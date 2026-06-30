"""Tool registration coverage and Tool-Naming Standard v1.1 compliance.

Backfills Rule 8 (CI verb guard) which was absent from hpo-link.

The register_* functions together must register EXACTLY the frozen TOOLS set,
and every name must be unprefixed snake_case starting with a ratified verb so it
composes cleanly behind a namespacing gateway (mounts under ``hpo``).

Ratified verb canon (Tool-Naming Standard v1.1, 2026-06-30):
  Tier-1 (universal read/query): get search list resolve find compare compute map
  Tier-2 (domain action/compute): predict annotate recode liftover analyze score
                                   submit export generate download
  ops/meta tag carve-out: tools tagged ``ops`` or ``meta`` skip the verb rule
    (still must match charset/length/no-self-prefix).
"""

from __future__ import annotations

import re

from hpo_link.mcp.capabilities import TOOLS
from hpo_link.mcp.facade import create_hpo_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
# Tier-1: full ratified read/query canon (Standard v1.1)
_TIER1_VERBS = frozenset({"get", "search", "list", "resolve", "find", "compare", "compute", "map"})
# Tier-2: sanctioned domain action/compute verbs (Standard v1.1)
_TIER2_VERBS = frozenset(
    {
        "predict",
        "annotate",
        "recode",
        "liftover",
        "analyze",
        "score",
        "submit",
        "export",
        "generate",
        "download",
    }
)
_CANONICAL_VERBS = _TIER1_VERBS | _TIER2_VERBS
_NAMESPACE = "hpo"


async def test_registered_tools_equal_frozen_tools() -> None:
    """The registered tool set must exactly match the declared TOOLS list."""
    mcp = create_hpo_mcp()
    names = {t.name for t in await mcp.list_tools()}
    assert names == set(TOOLS), (
        f"Registered: {sorted(names)}\nDeclared: {sorted(TOOLS)}\n"
        f"Extra: {sorted(names - set(TOOLS))}\n"
        f"Missing: {sorted(set(TOOLS) - names)}"
    )


async def test_tool_names_conform_to_standard_v1_1() -> None:
    """Every tool name must conform to Tool-Naming Standard v1.1.

    ops/meta-tagged tools skip the verb check but still must satisfy charset,
    length, and no-self-prefix rules.
    """
    mcp = create_hpo_mcp()
    tools = await mcp.list_tools()
    assert tools, "no tools registered"
    for tool in tools:
        name = tool.name
        tags = set(tool.tags or ())
        assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
        assert not name.startswith(f"{_NAMESPACE}_"), (
            f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace token"
        )
        # ops/meta utilities are exempt from the verb rule (fleet ops carve-out).
        if "ops" in tags or "meta" in tags:
            continue
        assert name.split("_", 1)[0] in _CANONICAL_VERBS, (
            f"{name!r} must start with a canonical verb {sorted(_CANONICAL_VERBS)}"
        )
