# -*- coding: utf-8 -*-
"""
Data Transfer Utilities
=======================

Handles Import/Export operations for Glossary and other data structures.
Supports: JSON, CSV (.csv), Excel (.xlsx)

JSON and CSV use only the standard library. Excel needs ``openpyxl``, which is
imported on demand so a missing package only disables .xlsx.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

_SOURCE_HEADERS = ("source", "original", "text", "id", "key")
_TARGET_HEADERS = ("target", "translation", "value", "translated", "tr")
# Excel writes ";" instead of "," in locales that use a decimal comma (Turkish, German, ...).
_CSV_DELIMITERS = ",;\t"


def _load_openpyxl():
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError("openpyxl required for Excel (.xlsx) import/export.") from exc
    return openpyxl


def _cell(row: Sequence, index: Optional[int]) -> str:
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _rows_to_glossary(rows: Iterable[Sequence]) -> Dict[str, str]:
    """Turn spreadsheet rows (first row = header) into {source: target}."""
    rows = iter(rows)
    header = next(rows, None)
    if header is None:
        return {}

    names = [str(c).strip().lower() if c is not None else "" for c in header]
    source_col = next((i for i, n in enumerate(names) if n in _SOURCE_HEADERS), None)
    target_col = next((i for i, n in enumerate(names) if n in _TARGET_HEADERS), None)

    if source_col is None:
        source_col = 0
    if target_col is None:
        target_col = next((i for i in range(len(names)) if i != source_col), None)

    glossary: Dict[str, str] = {}
    for row in rows:
        src = _cell(row, source_col)
        if src:
            glossary[src] = _cell(row, target_col)
    return glossary


def _read_csv_rows(path: Path) -> List[List[str]]:
    # utf-8-sig also reads files without a BOM; it drops the one Excel writes.
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        header = f.readline()
        f.seek(0)
        delimiter = max(_CSV_DELIMITERS, key=header.count)
        return list(csv.reader(f, delimiter=delimiter))


def export_glossary_to_file(glossary_data: Dict[str, str], filepath: str) -> bool:
    """Export glossary dict to JSON, XLSX, or CSV."""
    try:
        path = Path(filepath)
        ext = path.suffix.lower()

        if ext == ".json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(glossary_data, f, indent=2, ensure_ascii=False)
            return True

        elif ext == ".csv":
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "Target"])
                writer.writerows(glossary_data.items())
            return True

        elif ext == ".xlsx":
            openpyxl = _load_openpyxl()
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Glossary"
            sheet.append(["Source", "Target"])
            for source, target in glossary_data.items():
                sheet.append([source, target])
            # openpyxl turns any string starting with "=" into a formula; terms like
            # the emoticon "=)" must stay text.
            for row in sheet.iter_rows(min_row=2):
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        cell.data_type = "s"
            workbook.save(path)
            return True

        raise ValueError(f"Unsupported format: {ext}")
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise


def import_glossary_from_file(filepath: str) -> Dict[str, str]:
    """Import glossary from JSON, XLSX, or CSV file. Returns {source: target} dict."""
    try:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        ext = path.suffix.lower()
        glossary: Dict[str, str] = {}

        if ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                glossary = json.load(f)
            if not isinstance(glossary, dict):
                raise ValueError("Glossary JSON must be an object of {source: target} pairs.")

        elif ext == ".csv":
            glossary = _rows_to_glossary(_read_csv_rows(path))

        elif ext == ".xlsx":
            openpyxl = _load_openpyxl()
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                glossary = _rows_to_glossary(workbook.active.iter_rows(values_only=True))
            finally:
                workbook.close()

        else:
            raise ValueError(f"Unsupported format: {ext}")

        return glossary
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise
