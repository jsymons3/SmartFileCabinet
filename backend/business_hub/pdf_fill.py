"""CSV to PDF fill pipeline."""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from .models import PdfFillProfile, PdfFillRow


class PdfFillError(RuntimeError):
    """Raised when a PDF fill operation fails."""


@dataclass
class PlacementLog:
    row: PdfFillRow
    page_index: int
    font_size: float


DEFAULT_FONT = "Helvetica"


def parse_csv(csv_path: Path) -> List[PdfFillRow]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: List[PdfFillRow] = []
        for raw in reader:
            try:
                rows.append(
                    PdfFillRow(
                        id=str(raw.get("id")),
                        label=raw.get("label", ""),
                        x=float(raw.get("x", 0)),
                        y=float(raw.get("y", 0)),
                        value=raw.get("value", ""),
                        opt_font_size=float(raw["opt_font_size"]) if raw.get("opt_font_size") else None,
                        opt_page=int(raw["opt_page"]) if raw.get("opt_page") else None,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PdfFillError(f"Invalid row: {raw}") from exc
    return rows


def _draw_overlay(rows: Iterable[PdfFillRow], width: float, height: float, defaults: dict) -> io.BytesIO:
    buffer = io.BytesIO()
    font_size_default = defaults.get("fontSize", 10)
    c = canvas.Canvas(buffer, pagesize=(width, height))
    for row in rows:
        font_size = row.opt_font_size or font_size_default
        c.setFont(DEFAULT_FONT, font_size)
        c.drawString(row.x, row.y, row.value)
    c.save()
    buffer.seek(0)
    return buffer


def fill_pdf(template_path: Path, csv_path: Path, output_path: Optional[Path] = None, profile: Optional[PdfFillProfile] = None):
    if not template_path.exists():
        raise PdfFillError(f"Template not found: {template_path}")
    if not csv_path.exists():
        raise PdfFillError(f"CSV not found: {csv_path}")

    rows = parse_csv(csv_path)
    reader = PdfReader(str(template_path))
    writer = PdfWriter()

    defaults = profile.defaults if profile else {"fontSize": 10, "page": 1}
    page_groups: dict[int, List[PdfFillRow]] = {}
    for row in rows:
        page_index = (row.opt_page or defaults.get("page", 1)) - 1
        if page_index < 0 or page_index >= len(reader.pages):
            raise PdfFillError(f"Row {row.id} targets out-of-range page {page_index + 1}")
        page_groups.setdefault(page_index, []).append(row)

    placement_log: List[PlacementLog] = []

    for i, page in enumerate(reader.pages):
        page_copy = page
        overlays = page_groups.get(i)
        if overlays:
            media_box = page.mediabox
            width = float(media_box.width)
            height = float(media_box.height)
            overlay_pdf = _draw_overlay(overlays, width, height, defaults)
            overlay_reader = PdfReader(overlay_pdf)
            page_copy.merge_page(overlay_reader.pages[0])
            for row in overlays:
                placement_log.append(
                    PlacementLog(
                        row=row,
                        page_index=i,
                        font_size=row.opt_font_size or defaults.get("fontSize", 10),
                    )
                )
        writer.add_page(page_copy)

    output_path = output_path or template_path.with_name(f"filled_{uuid.uuid4().hex[:8]}.pdf")
    with output_path.open("wb") as handle:
        writer.write(handle)

    return output_path, placement_log


__all__ = [name for name in globals() if not name.startswith("_")]
