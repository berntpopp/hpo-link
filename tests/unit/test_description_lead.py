"""D1 (Tool-Schema Documentation v1.1): every tool description's first sentence says what it returns.

ponytail: the check is copied from genefoundry-router scripts/surface.py (`lead_states_return`);
re-vendor that module byte-identically if this repo ever vendors surface.py.
"""

from __future__ import annotations

import re

from hpo_link.mcp.facade import create_hpo_mcp

_LEAD_VERBS = (  # noqa: SIM905 - kept identical to router surface.py
    "get fetch retrieve list look lookup search find resolve report read predict annotate "
    "compute calculate count summarize summarise map translate convert describe show check "
    "validate classify score rank query browse discover explain compare diff normalize normalise "
    "expand evaluate assess enumerate identify locate export download match suggest recommend "
    "inspect generate render estimate"
).split()
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n\u2019t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|→|->",
    re.IGNORECASE,
)
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def _lead_states_return(description: str | None) -> bool:
    text = " ".join((description or "").split())
    lead = _SENTENCE_END.split(text, maxsplit=1)[0][:300]
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


async def test_every_tool_description_leads_with_what_it_returns() -> None:
    tools = await create_hpo_mcp().list_tools()
    failing = sorted(t.name for t in tools if not _lead_states_return(t.description))
    assert failing == [], f"D1: first sentence must state what the tool returns: {failing}"


def test_d1_check_rejects_a_usage_only_lead() -> None:
    assert not _lead_states_return("Use this when a caller needs constraint metrics for a gene.")
    assert _lead_states_return("Full-text search over terms; returns {hpo_id, name}.")
