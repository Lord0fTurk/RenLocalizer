"""Compare Regex and Stateful Lexer extraction without changing game files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.parser import RenPyParser
from src.utils.config import ConfigManager

EXCLUDED_PARTS = {"tl", "cache", "__pycache__", "python-packages", "lib", "common"}


@dataclass(frozen=True, slots=True)
class Record:
    file: str
    line: int
    text: str
    character: str
    text_type: str
    context: tuple[str, ...]

    @classmethod
    def from_entry(cls, entry: dict[str, object], root: Path) -> "Record":
        context = entry.get("context_path") or []
        return cls(
            file=str(Path(str(entry.get("file_path") or "")).relative_to(root)),
            line=int(entry.get("line_number") or 0),
            text=str(entry.get("text") or ""),
            character=str(entry.get("character") or ""),
            text_type=str(entry.get("text_type") or ""),
            context=tuple(str(value) for value in context),
        )

    @property
    def strict_key(self) -> tuple[str, str, str, tuple[str, ...]]:
        return self.file, self.text, self.character, self.context

    @property
    def text_key(self) -> str:
        return self.text

    @property
    def loose_key(self) -> tuple[str, str]:
        return self.file, self.text


def source_files(root: Path, single_file: Path | None = None) -> list[Path]:
    if single_file is not None:
        return [single_file]
    return sorted(
        path for path in root.rglob("*.rpy")
        if not EXCLUDED_PARTS.intersection(path.relative_to(root).parts)
    )


def isolated_config(stateful: bool) -> ConfigManager:
    config = ConfigManager()
    settings = config.translation_settings
    settings.enable_stateful_lexer = stateful
    settings.enable_deep_scan = False
    settings.enable_deep_extraction = False
    settings.enable_unrpyc_decompile = False
    settings.enable_rpyc_reader = False
    settings.deep_extraction_bare_defines = False
    settings.deep_extraction_bare_defaults = False
    return config


def extract(root: Path, stateful: bool, single_file: Path | None = None) -> tuple[list[Record], list[str]]:
    parser = RenPyParser(config_manager=isolated_config(stateful))
    records: list[Record] = []
    errors: list[str] = []
    for path in source_files(root, single_file):
        try:
            records.extend(
                Record.from_entry(entry, root)
                for entry in parser.extract_text_entries(path)
            )
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{path}: {type(error).__name__}: {error}")
    return records, errors


def duplicate_count(records: Iterable[Record]) -> int:
    counts = Counter(record.strict_key for record in records)
    return sum(count - 1 for count in counts.values() if count > 1)


def compare(root: Path, max_samples: int, single_file: Path | None = None) -> dict[str, object]:
    regex, regex_errors = extract(root, stateful=False, single_file=single_file)
    stateful, stateful_errors = extract(root, stateful=True, single_file=single_file)
    regex_keys = {record.strict_key for record in regex}
    stateful_keys = {record.strict_key for record in stateful}
    regex_texts = {record.loose_key for record in regex}
    stateful_texts = {record.loose_key for record in stateful}
    metadata_mismatches = sorted(
        {
            record.loose_key
            for record in stateful
            if record.strict_key not in regex_keys and record.loose_key in regex_texts
        }
    )

    def sample(records: Iterable[Record], keys: set[tuple[str, str, str, tuple[str, ...]]]) -> list[dict[str, object]]:
        return [asdict(record) for record in sorted(records, key=lambda item: item.strict_key) if record.strict_key in keys][:max_samples]

    return {
        "tool": "RenLocalizer lexer shadow comparison",
        "input": str(root),
        "files": len(source_files(root, single_file)),
        "regex": {"records": len(regex), "duplicates": duplicate_count(regex), "errors": regex_errors},
        "stateful": {"records": len(stateful), "duplicates": duplicate_count(stateful), "errors": stateful_errors},
        "comparison": {
            "exact_keys": len(regex_keys & stateful_keys),
            "stateful_only": len(stateful_keys - regex_keys),
            "regex_only": len(regex_keys - stateful_keys),
            "stateful_text_only": len(stateful_texts - regex_texts),
            "regex_text_only": len(regex_texts - stateful_texts),
            "metadata_mismatch_texts": len(metadata_mismatches),
            "stateful_only_samples": sample(stateful, stateful_keys - regex_keys),
            "regex_only_samples": sample(regex, regex_keys - stateful_keys),
        },
        "verdict": {
            "production_output_changed": False,
            "standalone_parity_claim": False,
            "note": "Stateful mode is compared against the existing parser; no game files are written.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="A game directory or .rpy file")
    parser.add_argument("-o", "--output", type=Path, help="Write the JSON report")
    parser.add_argument("--max-samples", type=int, default=25)
    args = parser.parse_args(argv)
    root = args.path if args.path.is_dir() else args.path.parent
    if not root.exists():
        parser.error(f"path does not exist: {args.path}")
    report = compare(root, max(0, args.max_samples), args.path if args.path.is_file() else None)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
