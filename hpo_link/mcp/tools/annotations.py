"""Annotation tools: gene/disease/phenotype cross-queries over the HPO index."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import cmd
from hpo_link.mcp.schemas import ANNOTATION_SCHEMA
from hpo_link.mcp.service_adapters import get_annotation_service
from hpo_link.mcp.tools._common import DiseaseIdStr, GeneStr, ResponseMode, TermStr

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_annotation_tools(mcp: FastMCP) -> None:
    """Register the HPO annotation cross-query tools on a FastMCP instance."""

    @mcp.tool(
        name="get_phenotypes_for_gene",
        title="Get HPO Phenotypes for Gene",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANNOTATION_SCHEMA,
        tags={"hpo", "annotation", "gene"},
        description=(
            "Return the HPO phenotype terms annotated to a gene (symbol or NCBI id). "
            "Signature: get_phenotypes_for_gene(gene, limit=, offset=, response_mode=)."
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_phenotypes_for_gene(
                gene, limit=limit, offset=offset, response_mode=response_mode
            )
            phenotypes = payload.get("phenotypes", [])
            steps: list[dict[str, Any]] = [cmd("get_diseases_for_gene", gene=gene)]
            if phenotypes and phenotypes[0].get("hpo_id"):
                steps.append(cmd("get_term", term=phenotypes[0]["hpo_id"]))
            payload.setdefault("_meta", {})["next_commands"] = steps
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
        output_schema=ANNOTATION_SCHEMA,
        tags={"hpo", "annotation", "gene"},
        description=(
            "Return the genes annotated to an HPO phenotype term, optionally expanded "
            "to include descendants. "
            "Signature: get_genes_for_phenotype(term, include_descendants=, limit=, "
            "offset=, response_mode=)."
        ),
    )
    async def get_genes_for_phenotype(
        term: TermStr,
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_genes_for_phenotype(
                term,
                limit=limit,
                offset=offset,
                include_descendants=include_descendants,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_diseases_for_phenotype", term=term),
                cmd("get_term", term=term),
            ]
            return payload

        return await run_mcp_tool(
            "get_genes_for_phenotype",
            call,
            context=McpErrorContext(
                "get_genes_for_phenotype",
                arguments={"term": term},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_phenotypes_for_disease",
        title="Get HPO Phenotypes for Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANNOTATION_SCHEMA,
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_phenotypes_for_disease(
                disease_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_genes_for_disease", disease_id=disease_id),
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
        output_schema=ANNOTATION_SCHEMA,
        tags={"hpo", "annotation", "disease"},
        description=(
            "Return diseases annotated to an HPO phenotype term, optionally expanded "
            "to include descendants. "
            "Signature: get_diseases_for_phenotype(term, include_descendants=, limit=, "
            "offset=, response_mode=)."
        ),
    )
    async def get_diseases_for_phenotype(
        term: TermStr,
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_diseases_for_phenotype(
                term,
                limit=limit,
                offset=offset,
                include_descendants=include_descendants,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_genes_for_phenotype", term=term),
                cmd("get_term", term=term),
            ]
            return payload

        return await run_mcp_tool(
            "get_diseases_for_phenotype",
            call,
            context=McpErrorContext(
                "get_diseases_for_phenotype",
                arguments={"term": term},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_genes_for_disease",
        title="Get Genes for Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANNOTATION_SCHEMA,
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_genes_for_disease(
                disease_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_phenotypes_for_disease", disease_id=disease_id),
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
        output_schema=ANNOTATION_SCHEMA,
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
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_annotation_service().get_diseases_for_gene(
                gene, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_phenotypes_for_gene", gene=gene),
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
