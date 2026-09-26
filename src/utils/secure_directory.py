"""Descriptor-relative directory traversal without following symbolic links."""

from __future__ import annotations

import errno
import os
from pathlib import Path


def open_directory(path: Path, *, create: bool = False) -> int:
    """Return an owned directory fd; caller must close it.

    Resolve components from the filesystem root, never through a path-based
    reopen. Existing directories retain their permissions; created ones use
    mode 0700. Symlinks and parent traversal are rejected with OSError.
    """
    path = Path(path)
    if ".." in path.parts:
        raise OSError(errno.EINVAL, "unsafe_directory")
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = child
        result = current
        current = None
        return result
    finally:
        if current is not None:
            os.close(current)
