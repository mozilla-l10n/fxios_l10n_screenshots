#!/usr/bin/env python3
"""Shared helpers for screenshot scripts."""

from __future__ import annotations

from pathlib import Path


def is_hidden(p: Path) -> bool:
    return p.name.startswith(".")


def iter_png_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        [
            p
            for p in folder.iterdir()
            if p.is_file() and not is_hidden(p) and p.suffix.lower() == ".png"
        ],
        key=lambda x: x.name,
    )
