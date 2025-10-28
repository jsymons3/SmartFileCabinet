"""Command line utilities for Business Hub."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from business_hub.models import PdfFillProfile
from business_hub.pdf_fill import PdfFillError, fill_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hub", description="Business Hub CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pdf_parser = subparsers.add_parser("pdf-fill", help="Fill a PDF from CSV coordinates")
    pdf_parser.add_argument("--template", required=True, type=Path)
    pdf_parser.add_argument("--csv", required=True, type=Path)
    pdf_parser.add_argument("--out", required=False, type=Path)
    pdf_parser.add_argument("--profile", required=False, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "pdf-fill":
        profile_obj = None
        if args.profile:
            profile_obj = PdfFillProfile(**json.loads(args.profile.read_text()))
        try:
            output_path, log = fill_pdf(
                template_path=args.template,
                csv_path=args.csv,
                output_path=args.out,
                profile=profile_obj,
            )
        except PdfFillError as exc:
            parser.error(str(exc))
            return 1
        print(f"PDF written to {output_path}")
        for placement in log:
            print(
                f"Row {placement.row.id} -> page {placement.page_index + 1} at ({placement.row.x},{placement.row.y})"
            )
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
