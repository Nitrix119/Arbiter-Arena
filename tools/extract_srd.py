"""Turn the SRD 5.1 PDF into page-marked plain text that agents can grep.

    python tools/extract_srd.py

Reads ``docs/SRD_CC_v5.1.pdf`` and writes ``docs/reference/srd_5.1.txt``. Both are
gitignored: the PDF is the CC-BY-4.0 edition from
https://dnd.wizards.com/resources/systems-reference-document, and the text is derived
from it. Needs ``pdftotext`` (Poppler) on the PATH.

Each page starts with a ``=== p.N ===`` marker. N is the PDF page, which in this
edition equals the number printed on the page, so ``SRD p.92`` means the same thing
in the text, in a PDF viewer, and on paper. See docs/current/SRD_FIDELITY.md §0.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "docs" / "SRD_CC_v5.1.pdf"
DEFAULT_OUT = ROOT / "docs" / "reference" / "srd_5.1.txt"


def clean_page(page: str) -> str:
    """Normalise one page of pdftotext output into readable, greppable lines."""
    # This PDF separates words with "\t\r ", so a bare \r is a word gap, not
    # a line break; only \r\n ends a line.
    page = page.replace("\r\n", "\n").replace("\r", " ")
    page = page.replace("­", "").replace("‐", "-").replace("‑", "-")
    page = re.sub(r"-{2,}", "-", page)
    page = re.sub(r"[ \t ]+", " ", page)
    page = "\n".join(line.strip() for line in page.splitlines())
    return re.sub(r"\n{3,}", "\n\n", page).strip()


def extract(pdf: Path, out: Path) -> int:
    """Write the page-marked text of ``pdf`` to ``out``; return the page count."""
    raw = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", "replace")
    pages = [
        f"=== p.{number} ===\n{clean_page(page)}\n"
        for number, page in enumerate(raw.split("\f"), 1)
        if page.strip()
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(pages), encoding="utf-8", newline="\n")
    return len(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(f"wrote {extract(args.pdf, args.out)} pages to {args.out}")


if __name__ == "__main__":
    main()
