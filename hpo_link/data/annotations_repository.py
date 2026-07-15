"""Annotation-query mixin for HpoRepository.

Provides gene/disease/phenotype cross-queries backed by the ``gene_phenotype``,
``disease_phenotype``, and ``gene_disease`` tables built by the HPO ingest pipeline.

This module is split from ``repository.py`` to keep both files under 500 lines.
"""

from __future__ import annotations

import sqlite3
from typing import Any

#: gene -> disease rows, LEFT JOINed to the disease label (issue #28 D3: the audit found
#: get_diseases_for_gene returned bare disease CURIEs with no disease_name in any mode). The
#: name lives in the HPOA-sourced disease_phenotype table keyed by database_id; a disease with
#: no phenotype annotations resolves to a NULL name (dropped in compact, kept as null in
#: standard/full). Only the WHERE clause differs between the symbol and ncbi lookups.
_DISEASES_FOR_GENE_SELECT = (
    "SELECT gd.ncbi_gene_id, gd.gene_symbol, gd.association_type, "
    "gd.disease_id, dn.disease_name, gd.source "
    "FROM gene_disease gd "
    "LEFT JOIN (SELECT database_id, disease_name FROM disease_phenotype GROUP BY database_id) "
    "dn ON dn.database_id = gd.disease_id "
)


class AnnotationsMixin:
    """Mixin that adds annotation queries to :class:`HpoRepository`.

    Expects ``self._conn`` to be a ``sqlite3.Connection`` (provided by the host
    class constructor).  No additional state is required.
    """

    _conn: sqlite3.Connection

    # -- gene -> phenotype -----------------------------------------------------

    def phenotypes_for_gene(
        self,
        kind: str,
        value: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """HPO phenotypes annotated to a gene.

        Args:
            kind: ``"ncbi"`` to match by NCBI gene id, ``"symbol"`` to match by
                gene symbol (case-insensitive).
            value: The gene identifier (numeric string for NCBI, symbol for symbol).
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with keys ``ncbi_gene_id``, ``gene_symbol``,
            ``hpo_id``, ``name``, ``frequency``, ``disease_id``.
        """
        col = "ncbi_gene_id" if kind == "ncbi" else "gene_symbol_upper"
        val = value if kind == "ncbi" else value.upper()
        rows = self._conn.execute(
            f"SELECT gp.ncbi_gene_id, gp.gene_symbol, gp.hpo_id, t.name, "  # noqa: S608
            f"gp.frequency, gp.disease_id "
            f"FROM gene_phenotype gp LEFT JOIN term t ON t.hpo_id = gp.hpo_id "
            f"WHERE gp.{col} = ? ORDER BY gp.hpo_id LIMIT ? OFFSET ?",
            (val, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_phenotypes_for_gene(self, kind: str, value: str) -> int:
        """Total HPO phenotypes annotated to a gene (for pagination)."""
        col = "ncbi_gene_id" if kind == "ncbi" else "gene_symbol_upper"
        val = value if kind == "ncbi" else value.upper()
        return int(
            self._conn.execute(
                f"SELECT COUNT(*) AS n FROM gene_phenotype WHERE {col} = ?",  # noqa: S608
                (val,),
            ).fetchone()["n"]
        )

    # -- phenotype -> gene -----------------------------------------------------

    def genes_for_phenotype(
        self,
        hpo_ids: list[str] | set[str],
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Distinct genes annotated to any of the given HPO ids.

        Args:
            hpo_ids: HPO term ids (e.g. ``["HP:0000479"]``).
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with keys ``ncbi_gene_id``, ``gene_symbol``.
        """
        ids = list(hpo_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT DISTINCT gp.ncbi_gene_id, gp.gene_symbol "  # noqa: S608
            f"FROM gene_phenotype gp "
            f"WHERE gp.hpo_id IN ({placeholders}) ORDER BY gp.gene_symbol LIMIT ? OFFSET ?",
            (*ids, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_genes_for_phenotype(self, hpo_ids: list[str] | set[str]) -> int:
        """Total distinct genes annotated to any of the given HPO ids."""
        ids = list(hpo_ids)
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        return int(
            self._conn.execute(
                f"SELECT COUNT(DISTINCT ncbi_gene_id) AS n "  # noqa: S608
                f"FROM gene_phenotype WHERE hpo_id IN ({placeholders})",
                tuple(ids),
            ).fetchone()["n"]
        )

    # -- disease -> phenotype --------------------------------------------------

    def phenotypes_for_disease(
        self,
        disease_id: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """HPO phenotypes annotated to a disease (from HPOA).

        Args:
            disease_id: Disease identifier, e.g. ``"OMIM:106210"``.
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with all ``disease_phenotype`` columns plus ``name``
            (HPO term name).
        """
        rows = self._conn.execute(
            "SELECT dp.database_id, dp.disease_name, dp.hpo_id, t.name, "
            "dp.qualifier, dp.reference, dp.evidence, dp.onset, dp.frequency, "
            "dp.frequency_hpo, dp.frequency_ratio, dp.frequency_percent, "
            "dp.sex, dp.modifier, dp.aspect, dp.biocuration "
            "FROM disease_phenotype dp LEFT JOIN term t ON t.hpo_id = dp.hpo_id "
            "WHERE dp.database_id = ? ORDER BY dp.hpo_id LIMIT ? OFFSET ?",
            (disease_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_phenotypes_for_disease(self, disease_id: str) -> int:
        """Total HPO phenotypes annotated to a disease (for pagination)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM disease_phenotype WHERE database_id = ?",
                (disease_id,),
            ).fetchone()["n"]
        )

    # -- phenotype -> disease --------------------------------------------------

    def diseases_for_phenotype(
        self,
        hpo_ids: list[str] | set[str],
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Distinct diseases annotated to any of the given HPO ids.

        Args:
            hpo_ids: HPO term ids.
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with keys ``database_id``, ``disease_name``.
        """
        ids = list(hpo_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT DISTINCT dp.database_id, dp.disease_name "  # noqa: S608
            f"FROM disease_phenotype dp "
            f"WHERE dp.hpo_id IN ({placeholders}) "
            f"ORDER BY dp.database_id LIMIT ? OFFSET ?",
            (*ids, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_diseases_for_phenotype(self, hpo_ids: list[str] | set[str]) -> int:
        """Total distinct diseases annotated to any of the given HPO ids."""
        ids = list(hpo_ids)
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        return int(
            self._conn.execute(
                f"SELECT COUNT(DISTINCT database_id) AS n "  # noqa: S608
                f"FROM disease_phenotype WHERE hpo_id IN ({placeholders})",
                tuple(ids),
            ).fetchone()["n"]
        )

    # -- disease -> gene -------------------------------------------------------

    def genes_for_disease(
        self,
        disease_id: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Genes associated with a disease (from gene_disease table).

        Args:
            disease_id: Disease identifier, e.g. ``"OMIM:106210"``.
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with keys ``ncbi_gene_id``, ``gene_symbol``,
            ``association_type``, ``disease_id``, ``source``.
        """
        rows = self._conn.execute(
            "SELECT gd.ncbi_gene_id, gd.gene_symbol, gd.association_type, "
            "gd.disease_id, gd.source "
            "FROM gene_disease gd "
            "WHERE gd.disease_id = ? ORDER BY gd.gene_symbol LIMIT ? OFFSET ?",
            (disease_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_genes_for_disease(self, disease_id: str) -> int:
        """Total genes associated with a disease (for pagination)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM gene_disease WHERE disease_id = ?",
                (disease_id,),
            ).fetchone()["n"]
        )

    # -- gene -> disease -------------------------------------------------------

    def diseases_for_gene(
        self,
        kind: str,
        value: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Diseases associated with a gene (from gene_disease table).

        Args:
            kind: ``"ncbi"`` to match by NCBI gene id, ``"symbol"`` to match by
                gene symbol (case-insensitive).
            value: The gene identifier.  For ``kind="ncbi"`` this may be a bare
                numeric id (``"5080"``) or a prefixed CURIE (``"NCBIGene:5080"``);
                both forms are matched because the ``gene_disease`` table stores
                the prefixed form while ``gene_phenotype`` stores the bare form.
            limit: Maximum rows to return.
            offset: Pagination offset.

        Returns:
            List of dicts with keys ``ncbi_gene_id``, ``gene_symbol``,
            ``association_type``, ``disease_id``, ``disease_name`` (from HPOA, may be
            ``None`` when the disease has no phenotype annotations), ``source``.
        """
        if kind == "symbol":
            rows = self._conn.execute(
                _DISEASES_FOR_GENE_SELECT
                + "WHERE gd.gene_symbol_upper = ? ORDER BY gd.disease_id LIMIT ? OFFSET ?",
                (value.upper(), limit, offset),
            ).fetchall()
        else:
            # Accept both bare "5080" and prefixed "NCBIGene:5080"
            ncbi_bare = value.removeprefix("NCBIGene:")
            ncbi_prefixed = f"NCBIGene:{ncbi_bare}"
            rows = self._conn.execute(
                _DISEASES_FOR_GENE_SELECT
                + "WHERE gd.ncbi_gene_id IN (?, ?) ORDER BY gd.disease_id LIMIT ? OFFSET ?",
                (ncbi_bare, ncbi_prefixed, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_diseases_for_gene(self, kind: str, value: str) -> int:
        """Total diseases associated with a gene (for pagination)."""
        if kind == "symbol":
            return int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM gene_disease WHERE gene_symbol_upper = ?",
                    (value.upper(),),
                ).fetchone()["n"]
            )
        ncbi_bare = value.removeprefix("NCBIGene:")
        ncbi_prefixed = f"NCBIGene:{ncbi_bare}"
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM gene_disease WHERE ncbi_gene_id IN (?, ?)",
                (ncbi_bare, ncbi_prefixed),
            ).fetchone()["n"]
        )
