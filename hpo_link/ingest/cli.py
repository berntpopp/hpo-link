"""Command-line interface for building and refreshing the HPO index.

Exposed as the ``hpo-link-data`` console script and intended as the cron entry
point. Commands: ``build`` (force a download + rebuild), ``refresh`` (conditional
rebuild -- the cron job), and ``status`` (print provenance of the existing DB).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from hpo_link.exceptions import DownloadError
from hpo_link.ingest.builder import BuildMeta, build_database, read_meta, rebuild
from hpo_link.ingest.downloader import download_bulk

if TYPE_CHECKING:
    from hpo_link.config import ServerSettings

app = typer.Typer(
    add_completion=False,
    help="Build and refresh the local HPO SQLite index from the hp.json + HPOA releases.",
)


def get_config() -> ServerSettings:
    """Return fresh server settings (data store) for the ingest CLI.

    Creates a new :class:`ServerSettings` each call so that environment
    variables injected by tests (e.g. via ``typer.testing.CliRunner``) are
    picked up instead of using the module-level singleton.
    """
    from hpo_link.config import ServerSettings

    return ServerSettings()


def _print_summary(meta: BuildMeta, *, header: str) -> None:
    """Print a compact provenance summary for a build."""
    print(header)
    print(f"  schema_version         : {meta.schema_version}")
    print(f"  hpo_version            : {meta.hpo_version}")
    print(f"  hpoa_version           : {meta.hpoa_version}")
    print(f"  terms                  : {meta.term_count}")
    print(f"  obsolete               : {meta.obsolete_count}")
    print(f"  closure rows           : {meta.closure_count}")
    print(f"  xref rows              : {meta.xref_count}")
    print(f"  disease_phenotype rows : {meta.disease_phenotype_count}")
    print(f"  gene_phenotype rows    : {meta.gene_phenotype_count}")
    print(f"  gene_disease rows      : {meta.gene_disease_count}")
    print(f"  built_utc              : {meta.build_utc}")
    print(f"  build_seconds          : {meta.build_duration_s}")


@app.command()
def build() -> None:
    """Force a download and full rebuild of the database."""
    config = get_config()
    try:
        results = download_bulk(config, force=True)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    paths = {key: r.path for key, r in results.items()}
    validators = {
        key: {"etag": r.etag, "last_modified": r.last_modified} for key, r in results.items()
    }
    meta = build_database(config, paths=paths, validators=validators)
    _print_summary(meta, header="Built HPO database:")


@app.command()
def refresh() -> None:
    """Conditionally refresh the database; rebuild only if the releases changed."""
    config = get_config()
    try:
        result = rebuild(config, force=False)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    if result.not_modified or result.meta is None:
        version = result.meta.hpo_version if result.meta else "unknown"
        print(f"HPO database is up to date (releases not modified; version {version}).")
        return
    _print_summary(result.meta, header="HPO database refreshed:")


@app.command()
def status() -> None:
    """Print provenance of the existing database, or a hint to build it."""
    config = get_config()
    meta = read_meta(config.data.db_path)
    if meta is None:
        print(f"No HPO database at {config.data.db_path}.")
        print("Run `hpo-link-data build` to download and build it.")
        raise typer.Exit(code=1)
    _print_summary(meta, header=f"HPO database at {config.data.db_path}:")


def main() -> None:
    """Console-script entry point for ``hpo-link-data``."""
    app()


if __name__ == "__main__":
    main()
