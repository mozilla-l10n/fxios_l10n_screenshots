#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

PONTOON_PROJECT_URL: str = "https://pontoon.mozilla.org/api/v2/projects/firefox-for-ios/"
ARTIFACT_BASE_URL: str = (
    "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/"
    "mobile.v2.firefox-ios.l10n-screenshots.latest.{locale}/artifacts/"
    "public%2FL10nScreenshotsTests%2F{locale}.zip"
)

USER_AGENT: str = "pontoon-l10n-screenshots-downloader/1.1"
CONNECT_TIMEOUT_S: float = 10.0
READ_TIMEOUT_S: float = 120.0

locale_mapping: dict[str, str] = {
    "ga-IE": "ga",
    "nb-NO": "nb",
    "nn-NO": "nn",
    "sat": "sat-Olck",
    "sv-SE": "sv",
    "templates": "en",
    "tl": "fil",
    "zgh": "tzm",
}

@dataclass(slots=True)
class Summary:
    eligible_locales: list[str]
    processed_locales: list[str]
    not_found_locales: list[str]
    failed_locales: list[tuple[str, str]]  # (locale, reason)


class ZipSlipError(RuntimeError):
    pass


def get_json(session: requests.Session, url: str) -> dict[str, Any]:
    r = session.get(url, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
    r.raise_for_status()
    data: Any = r.json()
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object from {url}, got {type(data).__name__}")
    return data


def eligible_locales(project_json: dict[str, Any]) -> list[str]:
    locs: Any = project_json.get("localizations")
    if not isinstance(locs, list):
        raise TypeError("Unexpected Pontoon response: `localizations` is not a list")

    eligible: set[str] = set()
    for entry in locs:
        if not isinstance(entry, dict):
            continue

        locale_obj: Any = entry.get("locale")
        if not isinstance(locale_obj, dict):
            continue

        code: Any = locale_obj.get("code")
        if not isinstance(code, str) or not code:
            continue

        approved: Any = entry.get("approved_strings")
        if isinstance(approved, int) and approved > 0:
            eligible.add(code)

    return sorted(eligible)


def download_zip(session: requests.Session, url: str) -> tuple[int, bytes | None]:
    r = session.get(url, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
    if r.status_code == 200:
        return 200, r.content
    return r.status_code, None


def safe_extract_zip(zip_bytes: bytes, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    base: Path = dest_dir.resolve()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # 3.11+: `Path.is_relative_to` is available and fast.
        for info in zf.infolist():
            target: Path = (base / info.filename).resolve()
            if not target.is_relative_to(base):
                raise ZipSlipError(f"Unsafe path in zip: {info.filename}")

        zf.extractall(base)


def process(output_dir: Path) -> Summary:
    processed: list[str] = []
    not_found: list[str] = []
    failed: list[tuple[str, str]] = []

    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT})

        project = get_json(session, PONTOON_PROJECT_URL)
        elig = eligible_locales(project)

        for locale in elig:
            url = ARTIFACT_BASE_URL.format(locale=locale_mapping.get(locale, locale))

            try:
                status, payload = download_zip(session, url)
            except requests.RequestException as e:
                failed.append((locale, f"request error: {e}"))
                continue

            if status == 404:
                not_found.append(locale)
                continue

            if status != 200 or payload is None:
                failed.append((locale, f"unexpected HTTP status {status}"))
                continue

            try:
                safe_extract_zip(payload, output_dir / locale)
                processed.append(locale)
            except (zipfile.BadZipFile, OSError, ZipSlipError) as e:
                failed.append((locale, f"extract error: {e}"))

    return Summary(
        eligible_locales=elig,
        processed_locales=processed,
        not_found_locales=not_found,
        failed_locales=failed,
    )


def print_summary(s: Summary) -> None:
    print(f"Eligible locales (approved_strings > 0): {len(s.eligible_locales)}\n")

    print(f"Processed OK: {len(s.processed_locales)}")
    if s.processed_locales:
        print("  " + ", ".join(s.processed_locales))
    print()

    print(f"404 Not Found: {len(s.not_found_locales)}")
    if s.not_found_locales:
        print("  " + ", ".join(s.not_found_locales))
    print()

    print(f"Other failures: {len(s.failed_locales)}")
    if s.failed_locales:
        for locale, reason in s.failed_locales:
            print(f"  {locale}: {reason}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download and extract iOS l10n screenshots ZIPs for Pontoon locales with approved strings."
    )
    p.add_argument(
        "output_dir",
        type=Path,
        help="Directory where ZIP contents will be extracted (per-locale subfolders will be created).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir: Path = args.output_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary = process(out_dir)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
