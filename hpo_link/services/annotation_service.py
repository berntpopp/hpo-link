"""Annotation service — gene/disease/phenotype cross-queries over the HPO index.

Wraps the low-level :class:`~hpo_link.data.repository.HpoRepository` annotation
methods with input validation, descendant expansion, pagination, and the
standard provenance fields (``hpo_version``, ``recommended_citation``).
"""

from __future__ import annotations

from typing import Any

from hpo_link.constants import RECOMMENDED_CITATION
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import InvalidInputError, NotFoundError
from hpo_link.identifiers import normalize_disease_id, normalize_gene
from hpo_link.services.pagination import page_fields
from hpo_link.services.resolution import Resolver

_DESCENDANT_LIMIT = 10_000


class AnnotationService:
    """Service layer for HPO annotation queries.

    Each public method validates its inputs, optionally expands a phenotype term
    to its transitive descendants, delegates to the repository, and returns a
    uniformly shaped ``dict`` that includes pagination fields and build provenance.
    """

    def __init__(self, repo: HpoRepository) -> None:
        """Bind the service to a pre-opened HPO repository."""
        self._repo = repo
        self._hpo_version: str | None = None

    # -- provenance ------------------------------------------------------------

    @property
    def _version(self) -> str | None:
        """Return the built HPO release string (lazily cached from meta table)."""
        if self._hpo_version is None:
            meta = self._repo.read_meta()
            self._hpo_version = meta.get("hpo_version") if meta else None
        return self._hpo_version

    # -- internal helpers ------------------------------------------------------

    def _resolve_to_id(self, term: str) -> str:
        """Resolve any HPO id / label / xref to a canonical HP id.

        Delegates to :class:`~hpo_link.services.resolution.Resolver` which
        raises :class:`~hpo_link.exceptions.NotFoundError` on a miss.
        """
        return Resolver(self._repo).resolve_term_id(term)

    def _expand_hpo_ids(self, hpo_id: str, include_descendants: bool) -> list[str]:
        """Return a sorted list of HPO ids: ``{hpo_id}`` optionally unioned with descendants."""
        ids: set[str] = {hpo_id}
        if include_descendants:
            for d in self._repo.descendants(hpo_id, limit=_DESCENDANT_LIMIT, offset=0):
                ids.add(d["hpo_id"])
        return sorted(ids)

    def _provenance(self) -> dict[str, str | None]:
        """Return the standard provenance block appended to every response."""
        return {
            "hpo_version": self._version,
            "recommended_citation": RECOMMENDED_CITATION,
        }

    # -- gene -> phenotype -----------------------------------------------------

    def get_phenotypes_for_gene(
        self,
        gene: str,
        limit: int = 25,
        offset: int = 0,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return HPO phenotypes annotated to a gene.

        Args:
            gene: Gene symbol (e.g. ``"PAX6"``), bare NCBI id (``"5080"``), or
                NCBI CURIE (``"NCBIGene:5080"``).
            limit: Maximum phenotypes to return per page.
            offset: Pagination offset.
            response_mode: Shaping hint (passed through; shaping done upstream).

        Returns:
            Dict with keys ``gene``, ``gene_kind``, ``gene_value``,
            ``phenotypes``, plus pagination fields and provenance.

        Raises:
            InvalidInputError: When ``gene`` is empty.
            NotFoundError: When the gene has no HPO annotations.
        """
        if not gene or not gene.strip():
            raise InvalidInputError("gene must be a non-empty gene symbol or NCBI id.", field="gene")

        kind, value = normalize_gene(gene)
        rows = self._repo.phenotypes_for_gene(kind, value, limit, offset)

        if not rows and offset == 0:
            total = self._repo.count_phenotypes_for_gene(kind, value)
            if total == 0:
                raise NotFoundError(
                    f"No HPO phenotype annotations found for gene '{gene}'.",
                )

        total = self._repo.count_phenotypes_for_gene(kind, value)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "gene": gene,
            "gene_kind": kind,
            "gene_value": value,
            "phenotypes": rows,
            **pag,
            **self._provenance(),
        }

    # -- phenotype -> gene -----------------------------------------------------

    def get_genes_for_phenotype(
        self,
        term: str,
        limit: int = 25,
        offset: int = 0,
        include_descendants: bool = False,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return genes annotated to an HPO phenotype (optionally expanded to descendants).

        Args:
            term: HPO id (``"HP:0000479"``), label, or xref CURIE to resolve.
            limit: Maximum genes to return per page.
            offset: Pagination offset.
            include_descendants: When ``True``, unions the term's transitive
                descendants before querying so genes annotated to any child term
                are included.
            response_mode: Shaping hint (passed through).

        Returns:
            Dict with keys ``term``, ``hpo_id``, ``genes``, ``include_descendants``,
            plus pagination fields and provenance.

        Raises:
            InvalidInputError: When ``term`` is empty (propagated from resolver).
            NotFoundError: When the term cannot be resolved.
        """
        hpo_id = self._resolve_to_id(term)
        hpo_ids = self._expand_hpo_ids(hpo_id, include_descendants)

        rows = self._repo.genes_for_phenotype(hpo_ids, limit, offset)
        total = self._repo.count_genes_for_phenotype(hpo_ids)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "term": term,
            "hpo_id": hpo_id,
            "genes": rows,
            "include_descendants": include_descendants,
            **pag,
            **self._provenance(),
        }

    # -- disease -> phenotype --------------------------------------------------

    def get_phenotypes_for_disease(
        self,
        disease_id: str,
        limit: int = 25,
        offset: int = 0,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return HPO phenotypes annotated to a disease (from HPOA).

        Args:
            disease_id: Disease CURIE, e.g. ``"OMIM:106210"`` or ``"ORPHA:123"``.
            limit: Maximum phenotypes to return per page.
            offset: Pagination offset.
            response_mode: Shaping hint (passed through).

        Returns:
            Dict with keys ``disease_id``, ``phenotypes``, plus pagination
            fields and provenance.

        Raises:
            InvalidInputError: When ``disease_id`` is empty.
        """
        if not disease_id or not disease_id.strip():
            raise InvalidInputError(
                "disease_id must be a non-empty disease CURIE (e.g. OMIM:106210).",
                field="disease_id",
            )

        disease_id = normalize_disease_id(disease_id)
        rows = self._repo.phenotypes_for_disease(disease_id, limit, offset)
        total = self._repo.count_phenotypes_for_disease(disease_id)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "disease_id": disease_id,
            "phenotypes": rows,
            **pag,
            **self._provenance(),
        }

    # -- phenotype -> disease --------------------------------------------------

    def get_diseases_for_phenotype(
        self,
        term: str,
        limit: int = 25,
        offset: int = 0,
        include_descendants: bool = False,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return diseases annotated to an HPO phenotype (optionally expanded to descendants).

        Args:
            term: HPO id, label, or xref CURIE to resolve.
            limit: Maximum diseases to return per page.
            offset: Pagination offset.
            include_descendants: When ``True``, unions the term's transitive
                descendants before querying.
            response_mode: Shaping hint (passed through).

        Returns:
            Dict with keys ``term``, ``hpo_id``, ``diseases``, ``include_descendants``,
            plus pagination fields and provenance.

        Raises:
            InvalidInputError: When ``term`` is empty (propagated from resolver).
            NotFoundError: When the term cannot be resolved.
        """
        hpo_id = self._resolve_to_id(term)
        hpo_ids = self._expand_hpo_ids(hpo_id, include_descendants)

        rows = self._repo.diseases_for_phenotype(hpo_ids, limit, offset)
        total = self._repo.count_diseases_for_phenotype(hpo_ids)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "term": term,
            "hpo_id": hpo_id,
            "diseases": rows,
            "include_descendants": include_descendants,
            **pag,
            **self._provenance(),
        }

    # -- disease -> gene -------------------------------------------------------

    def get_genes_for_disease(
        self,
        disease_id: str,
        limit: int = 25,
        offset: int = 0,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return genes associated with a disease (from gene_disease table).

        Args:
            disease_id: Disease CURIE, e.g. ``"OMIM:106210"``.
            limit: Maximum genes to return per page.
            offset: Pagination offset.
            response_mode: Shaping hint (passed through).

        Returns:
            Dict with keys ``disease_id``, ``genes``, plus pagination fields
            and provenance.

        Raises:
            InvalidInputError: When ``disease_id`` is empty.
        """
        if not disease_id or not disease_id.strip():
            raise InvalidInputError(
                "disease_id must be a non-empty disease CURIE (e.g. OMIM:106210).",
                field="disease_id",
            )

        disease_id = normalize_disease_id(disease_id)
        rows = self._repo.genes_for_disease(disease_id, limit, offset)
        total = self._repo.count_genes_for_disease(disease_id)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "disease_id": disease_id,
            "genes": rows,
            **pag,
            **self._provenance(),
        }

    # -- gene -> disease -------------------------------------------------------

    def get_diseases_for_gene(
        self,
        gene: str,
        limit: int = 25,
        offset: int = 0,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return diseases associated with a gene (from gene_disease table).

        Args:
            gene: Gene symbol (e.g. ``"PAX6"``), bare NCBI id (``"5080"``), or
                NCBI CURIE (``"NCBIGene:5080"``).
            limit: Maximum diseases to return per page.
            offset: Pagination offset.
            response_mode: Shaping hint (passed through).

        Returns:
            Dict with keys ``gene``, ``gene_kind``, ``gene_value``, ``diseases``,
            plus pagination fields and provenance.

        Raises:
            InvalidInputError: When ``gene`` is empty.
        """
        if not gene or not gene.strip():
            raise InvalidInputError(
                "gene must be a non-empty gene symbol or NCBI id.", field="gene"
            )

        kind, value = normalize_gene(gene)
        rows = self._repo.diseases_for_gene(kind, value, limit, offset)
        total = self._repo.count_diseases_for_gene(kind, value)
        pag = page_fields(total=total, returned=len(rows), limit=limit, offset=offset)

        return {
            "gene": gene,
            "gene_kind": kind,
            "gene_value": value,
            "diseases": rows,
            **pag,
            **self._provenance(),
        }
