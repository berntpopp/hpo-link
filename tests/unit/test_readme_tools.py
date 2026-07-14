"""The README '## Tools' table must match the registered tool surface exactly.

GeneFoundry README Standard v1, Rule 6: the table is machine-verified, not
hand-maintained. Adding, renaming, or removing a tool without updating the README
fails CI here.

The live tool list is obtained the same way ``test_tool_names.py`` obtains it —
from ``create_hpo_mcp()`` — so this test cannot drift from the real server.
"""

from __future__ import annotations

import re
from pathlib import Path

from hpo_link.mcp.facade import create_hpo_mcp

README = Path(__file__).resolve().parents[2] / "README.md"

_HEADING = "## Tools"
# A table row whose first cell is a single backticked tool name.
_TOOL_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|")


def _documented_tool_names() -> set[str]:
    """Parse the tool names out of the README's '## Tools' table."""
    lines = README.read_text(encoding="utf-8").splitlines()
    assert _HEADING in lines, f"README has no {_HEADING!r} section"
    start = lines.index(_HEADING)

    names: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## "):  # next section ends the table
            break
        match = _TOOL_ROW.match(line)
        if match:
            names.add(match.group(1))
    return names


async def test_readme_tools_table_matches_registered_tools() -> None:
    """The README table lists exactly the tools the server registers."""
    mcp = create_hpo_mcp()
    registered = {tool.name for tool in await mcp.list_tools()}
    documented = _documented_tool_names()

    assert documented == registered, (
        f"README '## Tools' table is out of sync with the server.\n"
        f"Undocumented (registered, missing from README): {sorted(registered - documented)}\n"
        f"Stale (in README, not registered): {sorted(documented - registered)}"
    )
