#!/usr/bin/env python3
"""
Sync localized PNG screenshots from NEW -> OLD with image comparison.

Rules:
- Locale folders are direct children of old/new root.
- Ignore hidden folders (starting with ".").
- Only process *.png (case-insensitive). Ignore hidden files.

For each locale:
1) If same filename exists in both: compare images while ignoring top-left status-bar time area.
   If different, copy NEW over OLD.
2) If a file exists in OLD but not in NEW: remove from OLD, and record it to report.
   If an entire locale folder is missing from NEW: warn, but do NOT delete the folder.
3) If a file exists in NEW but not in OLD: copy it into OLD.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable


TOP_IGNORE_PCT: float = 0.06
LEFT_IGNORE_PCT: float = 0.26


def is_hidden_path(p: Path) -> bool:
    return p.name.startswith(".")


def iter_locale_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and not is_hidden_path(p)],
        key=lambda x: x.name,
    )


def iter_png_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files: list[Path] = []
    for p in folder.iterdir():
        if p.is_file() and not is_hidden_path(p) and p.suffix.lower() == ".png":
            files.append(p)
    return sorted(files, key=lambda x: x.name)


def same_except_time(old_png: Path, new_png: Path) -> bool:
    """
    Perceptual-hash comparison outside an ignored top-left region defined as percentages.

    Returns True if the images are perceptually identical (hash distance == 0)
    after masking the top-left region; else False.
    """
    from PIL import Image  # type: ignore[import-not-found]
    import imagehash  # type: ignore[import-not-found]

    def masked_phash(p: Path) -> imagehash.ImageHash:
        im = Image.open(p).convert("RGB")
        w, h = im.size

        top = int(h * TOP_IGNORE_PCT)
        left = int(w * LEFT_IGNORE_PCT)

        masked = im.copy()
        # Mask out top-left region (time)
        masked.paste((0, 0, 0), (int(w * 0.1), int(h * 0.02), left, top))
        return imagehash.phash(masked)

    # If dimensions differ, treat as different
    with Image.open(old_png) as a_im, Image.open(new_png) as b_im:
        if a_im.size != b_im.size:
            return False

    return (masked_phash(old_png) - masked_phash(new_png)) == 0


@dataclass
class LocaleStats:
    locale: str
    changed: int = 0
    added: int = 0
    removed: int = 0
    removed_files: list[str] = field(default_factory=list)
    missing_in_new: bool = False


@dataclass
class Totals:
    changed: int = 0
    added: int = 0
    removed: int = 0


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def remove_file(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        return


def sync_locale(old_loc: Path, new_loc: Path | None) -> LocaleStats:
    stats = LocaleStats(locale=old_loc.name)

    if new_loc is None or not new_loc.exists():
        stats.missing_in_new = True
        return stats

    old_files = {p.name: p for p in iter_png_files(old_loc)}
    new_files = {p.name: p for p in iter_png_files(new_loc)}

    # 1) Same file exists: compare (ignore time). If different, overwrite OLD with NEW.
    for name in sorted(old_files.keys() & new_files.keys()):
        old_path = old_files[name]
        new_path = new_files[name]
        if not same_except_time(old_path, new_path):
            copy_file(new_path, old_path)
            stats.changed += 1

    # 2) Exists in OLD but not in NEW: remove from OLD, track for report.
    for name in sorted(old_files.keys() - new_files.keys()):
        old_path = old_files[name]
        remove_file(old_path)
        stats.removed += 1
        stats.removed_files.append(f"{old_loc.name}/{name}")

    # 3) Exists in NEW but not in OLD: copy into OLD.
    for name in sorted(new_files.keys() - old_files.keys()):
        new_path = new_files[name]
        dst = old_loc / name
        copy_file(new_path, dst)
        stats.added += 1

    return stats


def sync_all(
    old_root: Path, new_root: Path
) -> tuple[list[LocaleStats], Totals, list[str]]:
    old_locales = {p.name: p for p in iter_locale_dirs(old_root)}
    new_locales = {p.name: p for p in iter_locale_dirs(new_root)}

    stats_list: list[LocaleStats] = []
    warnings: list[str] = []

    totals = Totals()

    # Process locales that exist in OLD
    for locale in sorted(old_locales.keys()):
        old_loc = old_locales[locale]
        new_loc = new_locales.get(locale)

        st = sync_locale(old_loc, new_loc)
        stats_list.append(st)

        totals.changed += st.changed
        totals.added += st.added
        totals.removed += st.removed

        if st.missing_in_new:
            warnings.append(f"Locale folder missing in NEW (kept as-is): {locale}")

    # Locales that exist only in NEW: create in OLD and copy all PNGs.
    for locale in sorted(new_locales.keys() - old_locales.keys()):
        new_loc = new_locales[locale]
        old_loc = old_root / locale
        old_loc.mkdir(parents=True, exist_ok=True)

        st = LocaleStats(locale=locale)
        for png in iter_png_files(new_loc):
            copy_file(png, old_loc / png.name)
            st.added += 1

        stats_list.append(st)
        totals.added += st.added

    # Keep a combined removed list (to print at the end)
    removed_list: list[str] = []
    for st in stats_list:
        removed_list.extend(st.removed_files)

    return stats_list, totals, warnings


def print_report(
    stats_list: Iterable[LocaleStats],
    totals: Totals,
    warnings: list[str],
    removed_list: list[str],
) -> None:
    print("\nPer-locale summary:")
    for st in sorted(stats_list, key=lambda s: s.locale):
        extra = " (MISSING in NEW)" if st.missing_in_new else ""
        print(
            f"- {st.locale}{extra}: changed={st.changed}, added={st.added}, removed={st.removed}"
        )

    print("\nOverall summary:")
    print(f"- changed={totals.changed}, added={totals.added}, removed={totals.removed}")

    if removed_list:
        print("\nRemoved files:")
        for item in removed_list:
            print(f"- {item}")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"- {w}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sync locale PNG screenshots from NEW into OLD ignoring time in the image."
    )
    p.add_argument(
        "old", type=Path, help="Path to OLD root folder with existing images."
    )
    p.add_argument("new", type=Path, help="Path to NEW root folder with new images.")
    p.add_argument(
        "--top-ignore",
        type=float,
        default=TOP_IGNORE_PCT,
        help="Top fraction of image height to ignore (default: 0.10).",
    )
    p.add_argument(
        "--left-ignore",
        type=float,
        default=LEFT_IGNORE_PCT,
        help="Left fraction of image width to ignore (default: 0.30).",
    )
    return p.parse_args()


def main() -> None:
    global TOP_IGNORE_PCT, LEFT_IGNORE_PCT

    args = parse_args()
    TOP_IGNORE_PCT = args.top_ignore
    LEFT_IGNORE_PCT = args.left_ignore

    old_root: Path = args.old
    new_root: Path = args.new

    if not old_root.exists() or not old_root.is_dir():
        raise SystemExit(f"OLD root does not exist or is not a directory: {old_root}")
    if not new_root.exists() or not new_root.is_dir():
        raise SystemExit(f"NEW root does not exist or is not a directory: {new_root}")

    stats_list, totals, warnings = sync_all(old_root, new_root)
    removed_list: list[str] = []
    for st in stats_list:
        removed_list.extend(st.removed_files)

    print_report(stats_list, totals, warnings, removed_list)


if __name__ == "__main__":
    main()
