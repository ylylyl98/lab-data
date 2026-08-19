"""Storage-agnostic resolution of canonical experimental-data paths."""

from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

__all__ = ['StorageRoot']

_DRIVE_PATH = re.compile(r'^[A-Za-z]:')


def _parts(relative_path: str | Path) -> tuple[str, ...]:
    value = str(relative_path)
    if not value:
        raise ValueError('canonical relative path must not be empty')
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _DRIVE_PATH.match(normalized):
        raise ValueError(f'canonical path must be relative: {value}')
    components = tuple(normalized.split('/'))
    if '..' in components:
        raise ValueError(f'canonical path must not contain ..: {value}')
    filtered = tuple(component for component in components if component not in ('', '.'))
    if not filtered:
        raise ValueError('canonical relative path must not be empty')
    return filtered


def _is_absolute(value: str) -> bool:
    return Path(value).is_absolute() or ntpath.isabs(value)


@dataclass(frozen=True)
class StorageRoot:
    """Explicit authoritative storage root for runtime path resolution."""

    root: Path

    def __post_init__(self) -> None:
        root = Path(self.root)
        if not _is_absolute(str(root)):
            raise ValueError('storage root must be absolute')
        object.__setattr__(self, 'root', root)

    def resolve(self, relative_path: str | Path) -> Path:
        """Resolve a safe canonical relative path without requiring existence."""

        components = _parts(relative_path)
        return self.root.joinpath(*components)

    def canonicalize(self, path: str | Path) -> str:
        """Return the safe canonical path of an absolute path under this root."""

        value = str(path)
        if not _is_absolute(value):
            raise ValueError(f'path to canonicalize must be absolute: {value}')
        candidate = Path(value)
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f'path is outside storage root: {value}') from error
        components = _parts(relative)
        return PurePosixPath(*components).as_posix()

    canonical_relative_path = canonicalize
