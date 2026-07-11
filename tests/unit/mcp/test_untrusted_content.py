"""Structural untrusted-text fencing contracts."""

from __future__ import annotations

import hashlib

import pytest

from hpo_link.mcp.untrusted_content import (
    UntrustedTextLimitError,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)


def test_fence_normalizes_and_removes_forbidden_controls() -> None:
    raw = "Cafe\u0301\x00\u200b\u202e\nBRCA1"
    fenced = fence_untrusted_text(raw, source="hpo", record_id="HP:0001250")

    assert fenced.kind == "untrusted_text"
    assert fenced.text == "Caf\u00e9\nBRCA1"
    assert fenced.raw_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert fenced.provenance.source == "hpo"
    assert fenced.provenance.record_id == "HP:0001250"


def test_fence_preserves_tabs_newlines_and_scientific_symbols() -> None:
    raw = "p.Gly12Asp\t\u0394G = \u22121.2 kcal/mol\r\n"
    assert fence_untrusted_text(raw, source="hpo", record_id="HP:0001250").text == raw


def test_limits_reject_oversized_object() -> None:
    big = fence_untrusted_text("x" * 10, source="hpo", record_id="HP:0001250")
    with pytest.raises(UntrustedTextLimitError):
        enforce_untrusted_text_limits([big], max_text_bytes=5)


def test_search_snippet_fencing_preserves_internal_whitespace() -> None:
    """The compact snippet path must NOT collapse tab/LF/CR before fencing.

    Regression for the earlier ``" ".join(text.split())`` snippet that stripped
    internal whitespace before the fence, making ``raw_sha256`` cover rewritten
    text. The digest must be over the true pre-normalization snippet bytes.
    """
    from hpo_link.services.shaping import shape_search_hit

    raw = "Line one\twith tab\nLine two\r\nLine three"
    hit = {"hpo_id": "HP:0001250", "name": "Seizure", "score": -1.0, "definition": raw}
    shaped, fenced_objs = shape_search_hit(hit, "compact")

    fenced = shaped["definition_snippet"]
    # raw is short (< SEARCH_SNIPPET_CHARS=140) so the snippet equals the raw text
    assert fenced["text"] == raw
    assert "\t" in fenced["text"]
    assert "\n" in fenced["text"]
    assert fenced["raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(fenced_objs) == 1
