"""Construct and serialize NOMAD entry archives for optical experiments.

Pass S1 implements only the minimal local
:class:`~nomad.datamodel.EntryArchive` construction and native
JSON-compatible serialization. It wraps an
:class:`~lab_data.schema_packages.schema_package.OpticalExperiment` directly
as the archive ``data`` section and round-trips it through NOMAD's metainfo
serializer (``m_to_dict``). No files are written, no workflow or unrelated
fields are added, and nested structures are preserved for Pass S2.
"""

from __future__ import annotations

import json
from pathlib import Path

from nomad.datamodel import EntryArchive

from lab_data.schema_packages.schema_package import OpticalExperiment

__all__ = [
    'build_entry_archive',
    'serialize_entry_archive',
    'write_entry_archive_json',
]


def build_entry_archive(experiment: OpticalExperiment) -> EntryArchive:
    """Build a minimal entry archive whose data section is ``experiment``.

    The returned archive holds the supplied experiment directly as its
    ``data`` attribute. No workflow, metadata, or unrelated sections are
    populated, and the source experiment is never mutated.
    """

    return EntryArchive(data=experiment)


def serialize_entry_archive(archive: EntryArchive) -> dict:
    """Serialize an entry archive to a JSON-compatible dictionary.

    Uses NOMAD's native metainfo serialization
    (:meth:`EntryArchive.m_to_dict`) and validates the result with a strict
    :func:`json.dumps` call so any non-JSON-serializable value raises
    immediately. The archive is not mutated and no output file is written.
    """

    serialized = archive.m_to_dict()
    json.dumps(serialized)  # strict validation; raises on non-JSON types
    return serialized


def write_entry_archive_json(
    archive: EntryArchive, output_path: Path | str
) -> Path:
    """Serialize an entry archive and write it as deterministic UTF-8 JSON.

    Serializes the archive with :func:`serialize_entry_archive` and writes the
    result to the explicit caller-supplied ``output_path`` using
    :func:`json.dump` with stable key ordering (``sort_keys=True``) and
    two-space indentation. The parent directory is never created implicitly,
    no files are produced unless this function is called, and an existing
    target is refused with :class:`FileExistsError` so source data can never
    be overwritten by accident. Returns the resolved :class:`~pathlib.Path`
    that was written.
    """

    path = Path(output_path)
    if path.exists():
        raise FileExistsError(f'refusing to overwrite existing file: {path}')

    serialized = serialize_entry_archive(archive)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(serialized, handle, indent=2, sort_keys=True, ensure_ascii=False)

    return path
