#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
from pathlib import Path
from string import Template
from subprocess import check_output
from urllib.request import urlopen


PONTOON_PROJECT_API = "https://pontoon.mozilla.org/api/v2/projects/firefox-for-ios/"


def load_template(path: Path) -> Template:
    return Template(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def is_hidden(p: Path) -> bool:
    return p.name.startswith(".")


def fetch_locale_names() -> dict[str, str]:
    """
    Return mapping: locale_code -> locale_name
    """
    with urlopen(PONTOON_PROJECT_API) as r:  # nosec: trusted endpoint
        data = json.loads(r.read().decode("utf-8"))

    mapping: dict[str, str] = {}
    for item in data.get("localizations", []):
        loc = item.get("locale", {})
        code = loc.get("code")
        name = loc.get("name")
        if isinstance(code, str) and isinstance(name, str):
            mapping[code] = name
    return mapping


def iter_locale_dirs(repo_root: Path) -> list[Path]:
    """
    Locale folders are top-level directories in the repo.
    """
    out: list[Path] = []
    for p in repo_root.iterdir():
        if not p.is_dir():
            continue
        if is_hidden(p):
            continue
        if p.name in {".github", "site"}:
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.name)


def iter_png_files(locale_dir: Path) -> list[Path]:
    return sorted(
        [
            p
            for p in locale_dir.iterdir()
            if p.is_file() and not is_hidden(p) and p.suffix.lower() == ".png"
        ],
        key=lambda x: x.name,
    )


def commit_date_for_hash(repo_root: Path, commit: str) -> str:
    """
    Return commit date (ISO yyyy-mm-dd) for a given commit hash.
    """
    return check_output(
        ["git", "-C", str(repo_root), "show", "-s", "--format=%cs", commit],
        text=True,
    ).strip()


def latest_commit_for_path(repo_root: Path, rel_path: str) -> str:
    """
    Return latest commit hash that touched rel_path.
    """
    return check_output(
        ["git", "-C", str(repo_root), "log", "-1", "--format=%H", "--", rel_path],
        text=True,
    ).strip()


def build_site(repo_root: Path, out_dir: Path) -> None:
    owner_repo = os.environ.get(
        "GITHUB_REPOSITORY", "mozilla-l10n/fxios_l10n_screenshots"
    )

    templates_dir = repo_root / ".github/pages/templates"
    assets_dir = repo_root / ".github/pages/assets"

    base_tpl = load_template(templates_dir / "base.html")
    index_tpl = load_template(templates_dir / "index.html")
    locale_tpl = load_template(templates_dir / "locale.html")

    locale_names = fetch_locale_names()
    locales = iter_locale_dirs(repo_root)

    # Copy static assets
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    for asset in assets_dir.iterdir():
        if asset.is_file() and not is_hidden(asset):
            shutil.copy2(asset, out_dir / "assets" / asset.name)

    index_links: list[str] = []

    for loc_dir in locales:
        code = loc_dir.name
        name = locale_names.get(code, code)

        commit = latest_commit_for_path(repo_root, code)
        commit_date = commit_date_for_hash(repo_root, commit)
        commit_url = f"https://github.com/{owner_repo}/commit/{commit}"

        images_html: list[str] = []
        for png in iter_png_files(loc_dir):
            raw_url = (
                f"https://raw.githubusercontent.com/"
                f"{owner_repo}/{commit}/{code}/{png.name}"
            )
            images_html.append(
                f"""<figure>
  <figcaption>{html.escape(png.name)}</figcaption>
  <a href="{raw_url}">
    <img src="{raw_url}" alt="{html.escape(png.name)}"/>
  </a>
</figure>"""
            )

        locale_body = locale_tpl.substitute(
            locale_name=html.escape(name),
            locale_code=html.escape(code),
            commit_date=commit_date,
            commit_url=commit_url,
            images="\n".join(images_html) or '<p class="muted">No images.</p>',
            base_path="..",
        )

        page = base_tpl.substitute(
            title=f"{name} ({code})",
            body=locale_body,
            base_path="..",
        )

        write_text(out_dir / code / "index.html", page)

        index_links.append(
            f'<div><a href="{code}/">{html.escape(name)} ({html.escape(code)})</a></div>'
        )

    index_body = index_tpl.substitute(locale_links="\n".join(index_links))
    index_page = base_tpl.substitute(
        title="Firefox for iOS screenshots",
        body=index_body,
        base_path=".",
    )
    write_text(out_dir / "index.html", index_page)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build static GitHub Pages for screenshots."
    )
    p.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Path to repository root containing locale folders.",
    )
    p.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Destination directory for generated site.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    repo_root = args.repo.resolve()
    out_dir = args.dest.resolve()

    if not repo_root.is_dir():
        raise SystemExit(f"Invalid --repo path: {repo_root}")

    # Clean destination
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    build_site(repo_root, out_dir)
    print(f"Built site from {repo_root} into {out_dir}")


if __name__ == "__main__":
    main()
