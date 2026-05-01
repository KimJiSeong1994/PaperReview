"""Regression checks for the README service GIF walkthrough."""

from __future__ import annotations

import re
import struct
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = PROJECT_ROOT / "README.md"
GIF_PATH = PROJECT_ROOT / "docs" / "images" / "jiphyeonjeon-workflow.gif"


def test_readme_embeds_service_gif_with_resolving_relative_path() -> None:
    """The README should point at the checked-in service walkthrough GIF."""
    readme_text = README.read_text(encoding="utf-8")

    image_match = re.search(
        r'<img\s+src="(?P<src>docs/images/jiphyeonjeon-workflow\.gif)"\s+'
        r'alt="(?P<alt>[^"]+)"',
        readme_text,
    )

    assert image_match is not None
    assert (PROJECT_ROOT / image_match.group("src")).is_file()
    assert "workflow" in image_match.group("alt")


def test_service_gif_is_real_widescreen_asset() -> None:
    """Guard against replacing the README walkthrough with a missing/tiny stub."""
    gif_bytes = GIF_PATH.read_bytes()

    assert gif_bytes.startswith((b"GIF87a", b"GIF89a"))
    width, height = struct.unpack("<HH", gif_bytes[6:10])
    assert (width, height) == (1280, 720)
    assert GIF_PATH.stat().st_size > 500_000
    assert gif_bytes.count(b"\x2c") >= 9  # multiple walkthrough frames, not a static placeholder
