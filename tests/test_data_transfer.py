# -*- coding: utf-8 -*-
"""Glossary import/export (JSON, CSV, XLSX) without pandas."""

from pathlib import Path

import pytest

from src.utils import data_transfer
from src.utils.data_transfer import export_glossary_to_file, import_glossary_from_file

GLOSSARY = {"HP": "Can Puanı", "Penny": "Penny", "Save, Load": "Kaydet; Yükle", "=)": "gülen yüz"}


def test_module_does_not_depend_on_pandas() -> None:
    # pandas was never in requirements.txt nor in the release bundle.
    assert "pandas" not in Path(data_transfer.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("ext", [".json", ".csv"])
def test_round_trip(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"glossary{ext}"
    assert export_glossary_to_file(GLOSSARY, str(path)) is True
    assert import_glossary_from_file(str(path)) == GLOSSARY


def test_xlsx_round_trip_keeps_formula_like_terms_as_text(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    path = tmp_path / "glossary.xlsx"
    assert export_glossary_to_file(GLOSSARY, str(path)) is True
    assert import_glossary_from_file(str(path)) == GLOSSARY


def test_csv_export_has_bom_and_header(tmp_path: Path) -> None:
    path = tmp_path / "glossary.csv"
    export_glossary_to_file({"HP": "Can"}, str(path))
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8-sig").splitlines()[0] == "Source,Target"


def test_csv_import_accepts_semicolon_delimiter_from_excel(tmp_path: Path) -> None:
    path = tmp_path / "excel_tr.csv"
    path.write_text("Source;Target\nHP;Can Puanı\nMP;Mana\n", encoding="utf-8-sig")
    assert import_glossary_from_file(str(path)) == {"HP": "Can Puanı", "MP": "Mana"}


def test_csv_import_recognises_header_aliases_in_any_order(tmp_path: Path) -> None:
    path = tmp_path / "aliases.csv"
    path.write_text("Translation,Original,Notes\nCan Puanı,HP,stat\n", encoding="utf-8")
    assert import_glossary_from_file(str(path)) == {"HP": "Can Puanı"}


def test_csv_import_falls_back_to_first_two_columns(tmp_path: Path) -> None:
    path = tmp_path / "plain.csv"
    path.write_text("Term,Meaning\nHP,Can Puanı\n", encoding="utf-8")
    assert import_glossary_from_file(str(path)) == {"HP": "Can Puanı"}


def test_csv_import_skips_blank_sources_and_keeps_empty_targets(tmp_path: Path) -> None:
    path = tmp_path / "gaps.csv"
    path.write_text("Source,Target\n,orphan\nPenny,\n  Rose  ,  Gül \n", encoding="utf-8")
    assert import_glossary_from_file(str(path)) == {"Penny": "", "Rose": "Gül"}


def test_empty_csv_gives_empty_glossary(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert import_glossary_from_file(str(path)) == {}


def test_json_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text('["HP", "MP"]', encoding="utf-8")
    with pytest.raises(ValueError):
        import_glossary_from_file(str(path))


def test_unsupported_format_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        export_glossary_to_file({"a": "b"}, str(tmp_path / "glossary.xls"))
    with pytest.raises(FileNotFoundError):
        import_glossary_from_file(str(tmp_path / "missing.csv"))


def test_xlsx_without_openpyxl_reports_a_clear_error(tmp_path: Path, monkeypatch) -> None:
    def _missing():
        raise ImportError("openpyxl required for Excel (.xlsx) import/export.")

    monkeypatch.setattr(data_transfer, "_load_openpyxl", _missing)
    with pytest.raises(ImportError, match="openpyxl"):
        export_glossary_to_file({"a": "b"}, str(tmp_path / "g.xlsx"))
    # JSON and CSV keep working without it.
    export_glossary_to_file({"a": "b"}, str(tmp_path / "g.csv"))
    assert import_glossary_from_file(str(tmp_path / "g.csv")) == {"a": "b"}
