from __future__ import annotations

import csv
from pathlib import Path

from reportlab.pdfgen import canvas

from business_hub.pdf_fill import fill_pdf


def make_template(path: Path) -> None:
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Invoice Template")
    c.showPage()
    c.save()


def write_csv(path: Path) -> None:
    rows = [
        {"id": "1", "label": "Vendor", "x": "72", "y": "680", "value": "Acme"},
        {"id": "2", "label": "Total", "x": "400", "y": "200", "value": "$100"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "label", "x", "y", "value"])
        writer.writeheader()
        writer.writerows(rows)


def test_fill_pdf(tmp_path: Path) -> None:
    template = tmp_path / "template.pdf"
    csv_path = tmp_path / "fields.csv"
    make_template(template)
    write_csv(csv_path)

    output, log = fill_pdf(template, csv_path)
    assert output.exists()
    assert len(log) == 2
