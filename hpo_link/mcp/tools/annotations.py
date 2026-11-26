"""Annotation tools: gene/disease/phenotype cross-queries over the HPO index."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import cmd, echo_safe, foreign_id_converter, page_cmd
from hpo_link.mcp.service_adapters import get_annotation_service
from hpo_link.mcp.tools._common import DiseaseIdStr, GeneStr, ResponseMode, ToolReturn

if TYPE_CHECKING:
    from fastmcp import FastMCP

HpoIdStr = Annotated[
    str,
    Field(
        description=(
            "Canonical HP id for the resolved HPO phenotype (HP:0000118). Legacy `term` "
            "arguments are accepted as an alias."
        ),
        examples=["HP:0000118"],
    ),
]


def register_annotation_tools(mcp: FastMCP) -> None:
    """Register the HPO annotation cross-query tools on a FastMCP instance."""

    @mcp.tool(
        name="get_phenotypes_for_gene",
        title="Get HPO Phenotypes for Gene",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "gene"},
        description=(
            "Return the HPO phenotype terms annotated to a gene (symbol or NCBI id). "
            "Signature: get_phenotypes_for_gene(gene, limit=, offset=, response_mode=). "
            "For several phenotypes and/or a candidate gene list at once, use "
            "score_genes_for_phenotypes instead of looping over single-gene calls."
        ),
    )
    async def get_phenotypes_for_gene(
        gene: GeneStr,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max phenotypes to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_phenotypes_for_gene(
                gene, limit=limit, offset=offset, response_mode=response_mode
            )
            phenotypes = payload.get("phenotypes", [])
            # Chain the gene only once the index matched it (GTS-CORE-TXT-04).
            steps: list[dict[str, Any]] = (
                [cmd("get_diseases_for_gene", gene=gene)] if payload.get("total") else []
            )
            if phenotypes and phenotypes[0].get("hpo_id"):
                steps.append(cmd("get_term", term=phenotypes[0]["hpo_id"]))
            payload.setdefault("_meta", {})["next_commands"] = steps or [
                cmd("get_server_capabilities")
            ]
            return payload

        return await run_mcp_tool(
            "get_phenotypes_for_gene",
            call,
            context=McpErrorContext(
                "get_phenotypes_for_gene",
                arguments={"gene": gene},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_genes_for_phenotype",
        title="Get Genes for HPO Phenotype",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "gene"},
        description=(
            "Return the genes annotated to an HPO phenotype term, optionally expanded "
            "to include descendants. "
            "Signature: get_genes_for_phenotype(hpo_id, include_descendants=, limit=, "
            "offset=, response_mode=). "
            "For several phenotypes and/or a candidate gene list at once, use "
            "score_genes_for_phenotypes instead of looping over single-term calls."
        ),
    )
    async def get_genes_for_phenotype(
        hpo_id: HpoIdStr,
        include_descendants: Annotated[
            bool,
            Field(
                description=(
                    "When true, unions the term's transitive descendants so genes "
                    "annotated to any child term are included (default false)."
                )
            ),
        ] = False,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max genes to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_genes_for_phenotype(
                hpo_id,
                limit=limit,
                offset=offset,
                include_descendants=include_descendants,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_diseases_for_phenotype", hpo_id=payload["hpo_id"]),
                cmd("get_term", hpo_id=payload["hpo_id"]),
            ]
            return payload

        return await run_mcp_tool(
            "get_genes_for_phenotype",
            call,
            context=McpErrorContext(
                "get_genes_for_phenotype",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_phenotypes_for_disease",
        title="Get HPO Phenotypes for Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "disease"},
        description=(
            "Return the HPO phenotype terms annotated to a disease CURIE "
            "(e.g. OMIM:106210, ORPHA:550). "
            "Signature: get_phenotypes_for_disease(disease_id, limit=, offset=, "
            "response_mode=)."
        ),
    )
    async def get_phenotypes_for_disease(
        disease_id: DiseaseIdStr,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max phenotypes to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_phenotypes_for_disease(
                disease_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_genes_for_disease", disease_id=payload["disease_id"])
                if payload.get("total")
                else cmd("get_server_capabilities")
            ]
            return payload

        return await run_mcp_tool(
            "get_phenotypes_for_disease",
            call,
            context=McpErrorContext(
                "get_phenotypes_for_disease",
                arguments={"disease_id": disease_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_diseases_for_phenotype",
        title="Get Diseases for HPO Phenotype",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "disease"},
        description=(
            "Return diseases annotated to an HPO phenotype term, optionally expanded "
            "to include descendants. "
            "Signature: get_diseases_for_phenotype(hpo_id, include_descendants=, limit=, "
            "offset=, response_mode=)."
        ),
    )
    async def get_diseases_for_phenotype(
        hpo_id: HpoIdStr,
        include_descendants: Annotated[
            bool,
            Field(
                description=(
                    "When true, unions the term's transitive descendants so diseases "
                    "annotated to any child term are included (default false)."
                )
            ),
        ] = False,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max diseases to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_diseases_for_phenotype(
                hpo_id,
                limit=limit,
                offset=offset,
                include_descendants=include_descendants,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_genes_for_phenotype", hpo_id=payload["hpo_id"]),
                cmd("get_term", hpo_id=payload["hpo_id"]),
            ]
            return payload

        return await run_mcp_tool(
            "get_diseases_for_phenotype",
            call,
            context=McpErrorContext(
                "get_diseases_for_phenotype",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_genes_for_disease",
        title="Get Genes for Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "gene", "disease"},
        description=(
            "Return genes associated with a disease CURIE (e.g. OMIM:106210, ORPHA:550). "
            "Signature: get_genes_for_disease(disease_id, limit=, offset=, response_mode=)."
        ),
    )
    async def get_genes_for_disease(
        disease_id: DiseaseIdStr,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max genes to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_genes_for_disease(
                disease_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_phenotypes_for_disease", disease_id=payload["disease_id"])
                if payload.get("total")
                else cmd("get_server_capabilities")
            ]
            return payload

        return await run_mcp_tool(
            "get_genes_for_disease",
            call,
            context=McpErrorContext(
                "get_genes_for_disease",
                arguments={"disease_id": disease_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_diseases_for_gene",
        title="Get Diseases for Gene",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "gene", "disease"},
        description=(
            "Return diseases associated with a gene (symbol or NCBI id). "
            "Signature: get_diseases_for_gene(gene, limit=, offset=, response_mode=)."
        ),
    )
    async def get_diseases_for_gene(
        gene: GeneStr,
        limit: Annotated[
            int, Field(ge=1, le=200, description="Max diseases to return (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_diseases_for_gene(
                gene, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_phenotypes_for_gene", gene=gene)
                if payload.get("total")
                else cmd("get_server_capabilities")
            ]
            return payload

        return await run_mcp_tool(
            "get_diseases_for_gene",
            call,
            context=McpErrorContext(
                "get_diseases_for_gene",
                arguments={"gene": gene},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="score_genes_for_phenotypes",
        title="Score Genes for HPO Phenotypes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "annotation", "gene", "ranking"},
        description=(
            "Rank genes for a set of HPO phenotype terms (Resnik similarity to annotated "
            "diseases); returns ranked candidate genes for a patient's phenotypes, each with "
            "score, best disease and matched term pairs (shared ancestor + IC); excluded "
            "terms are reported as conflicts, never scored. Every input HP id is scored as "
            "given, listed in replaced_hpo_ids (obsolete id or alt_id, scored as replaced_by) "
            "or listed in ignored_hpo_ids with a reason. "
            "close_call=true (with rank1_margin) means the top ranks are too close to pick "
            "rank 1 by score alone; close_call=false does not confirm rank 1. In minimal mode "
            "top_matches reads '<input id> = <disease term>' for the same term, '~' for a "
            "related one, f=? when no frequency is recorded. "
            "Signature: score_genes_for_phenotypes(hpo_ids, excluded_hpo_ids=, "
            "candidate_genes=, limit=, offset=, response_mode=)."
        ),
    )
    async def score_genes_for_phenotypes(
        hpo_ids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="Present patient phenotypes as HP ids (e.g. HP:0001250).",
                examples=[["HP:0001250", "HP:0001263"]],
            ),
        ],
        excluded_hpo_ids: Annotated[
            list[str] | None,
            Field(
                max_length=100,
                description=(
                    "Phenotypes observed ABSENT. Reported as conflicts on each gene's best "
                    "disease; they never lower a score."
                ),
                examples=[["HP:0001250"]],
            ),
        ] = None,
        candidate_genes: Annotated[
            list[str] | None,
            Field(
                max_length=5000,
                description=(
                    "Restrict ranking to these genes (e.g. genes with exome variants): gene "
                    "symbols (SCN1A) or NCBI gene ids (NCBIGene:6323 or 6323). Ensembl gene "
                    "(ENSG...), HGNC (HGNC:...) and RefSeq ids are not mapped here: translate "
                    "the list with hgnc_resolve_symbols_batch first (transcript ids, ENST..., "
                    "are not gene ids). Each ranked row echoes the "
                    "caller's spelling as input_id; entries that cannot be ranked are listed in "
                    "unranked_candidate_genes as {input_id, reason} "
                    "(unsupported_identifier | not_rankable)."
                ),
                examples=[["SCN1A", "KCNQ2", "STXBP1"], ["NCBIGene:6323", "3785"]],
            ),
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Max genes to return (default 20).")
        ] = 20,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        args: dict[str, Any] = {"hpo_ids": hpo_ids}
        if excluded_hpo_ids:
            args["excluded_hpo_ids"] = excluded_hpo_ids
        if candidate_genes is not None:
            args["candidate_genes"] = candidate_genes

        async def call() -> dict[str, Any]:
            payload = get_annotation_service().score_genes_for_phenotypes(
                hpo_ids,
                excluded_hpo_ids=excluded_hpo_ids,
                candidate_genes=candidate_genes,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
            # Unsupported ids in a mixed list: hand them to the converter, ready to send.
            unsupported = [
                u["input_id"]
                for u in payload["unranked_candidate_genes"]
                if u["reason"] == "unsupported_identifier"
            ]
            steps = foreign_id_converter("candidate_genes", {"candidate_genes": unsupported})
            if payload["close_call"]:  # curated gene-disease links HPO may lack; takes symbols
                steps.append(cmd("gencc_get_genes_curations", genes=payload["close_call_genes"]))
            if payload.get("truncated") and all(
                echo_safe(v)
                for v in [*hpo_ids, *(excluded_hpo_ids or []), *(candidate_genes or [])]
            ):
                steps.append(
                    page_cmd(
                        "score_genes_for_phenotypes",
                        {**args, "limit": limit},
                        payload["next_offset"],
                    )
                )
            if payload["genes"]:
                top = payload["genes"][0]
                steps.append(cmd("get_phenotypes_for_gene", gene=top["gene"]))
                steps.append(
                    cmd("get_phenotypes_for_disease", disease_id=top["best_disease"]["disease_id"])
                )
            payload.setdefault("_meta", {})["next_commands"] = steps
            return payload

        return await run_mcp_tool(
            "score_genes_for_phenotypes",
            call,
            context=McpErrorContext(
                "score_genes_for_phenotypes", arguments=args, response_mode=response_mode
            ),
        )
