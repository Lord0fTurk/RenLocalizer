"""Coverage / Diagnostic reporting for RenLocalizer pipeline.

Small helper to collect extraction/translation/save events and emit
a JSON report summarizing counts and per-file details.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class FileReport:
    file_path: str
    extracted: int = 0
    translated: int = 0
    written: int = 0
    skipped: int = 0
    unchanged: int = 0
    blocked: int = 0
    recovered_retry: int = 0
    recovered_variant: int = 0
    normalized_wrapper: int = 0
    entries: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    project: str = ''
    target_language: str = ''
    total_extracted: int = 0
    total_translated: int = 0
    total_written: int = 0
    total_skipped: int = 0
    total_unchanged: int = 0
    total_unchanged_by_engine: int = 0
    total_blocked_as_corrupted: int = 0
    total_recovered_by_retry: int = 0
    total_recovered_by_synthesized_variant: int = 0
    total_normalized_wrapper: int = 0
    engine: str = ''
    model: str = ''
    stage_provenance: Dict[str, Any] = field(default_factory=dict)
    unchanged_reasons: Dict[str, int] = field(default_factory=dict)
    alias_kinds: Dict[str, int] = field(default_factory=dict)
    files: Dict[str, FileReport] = field(default_factory=dict)
    coverage_warnings: List[Dict[str, Any]] = field(default_factory=list)

    def add_extracted(self, file_path: str, entry: Dict[str, Any]):
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.extracted += 1
        rec = {**entry, 'status': 'extracted'}
        if 'raw_text' in entry and entry.get('raw_text') is not None:
            rec['raw_text'] = entry.get('raw_text')
        # If a translation_id is supplied or can be computed externally, include it.
        if 'translation_id' in entry and entry.get('translation_id'):
            rec['translation_id'] = entry.get('translation_id')
        fr.entries.append(rec)
        self.total_extracted += 1

    def mark_translated(
        self,
        file_path: str,
        translation_id: str,
        translated_text: str,
        original_text: str = None,
    ) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.translated += 1
        rec = {'translation_id': translation_id, 'translated_text': translated_text, 'status': 'translated'}
        if original_text is not None:
            rec['original_text'] = original_text
        fr.entries.append(rec)
        self.total_translated += 1

    def mark_written(self, file_path: str, translation_id: str) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.written += 1
        fr.entries.append({'translation_id': translation_id, 'status': 'written'})
        self.total_written += 1

    def mark_skipped(self, file_path: str, reason: str, entry: Dict[str, Any] = None) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.skipped += 1
        rec = {'status': 'skipped', 'reason': reason}
        if entry:
            rec.update(entry)
        fr.entries.append(rec)
        self.total_skipped += 1

    def mark_unchanged(
        self,
        file_path: str,
        translation_id: str,
        original_text: str = None,
        reason: str | None = None,
    ) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.unchanged += 1
        rec = {'translation_id': translation_id, 'status': 'unchanged'}
        if original_text is not None:
            rec['original_text'] = original_text
        if reason:
            rec['reason'] = reason
            self.unchanged_reasons[reason] = self.unchanged_reasons.get(reason, 0) + 1
        fr.entries.append(rec)
        self.total_unchanged += 1
        if reason in ('unchanged_core_ui', 'unchanged_sentence', 'core_ui', 'sentence'):
            self.total_unchanged_by_engine += 1

    def mark_normalized_wrapper(
        self,
        file_path: str,
        translation_id: str,
        *,
        original_text: str | None = None,
        translated_text: str | None = None,
        normalized_text: str | None = None,
    ) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.normalized_wrapper += 1
        self.total_normalized_wrapper += 1
        rec: Dict[str, Any] = {
            'translation_id': translation_id,
            'status': 'normalized',
            'reason': 'outer_color_wrapper',
        }
        if original_text is not None:
            rec['original_text'] = original_text
        if translated_text is not None:
            rec['translated_text'] = translated_text
        if normalized_text is not None:
            rec['normalized_text'] = normalized_text
        fr.entries.append(rec)

    def set_provenance(self, engine: str, model: str = '', **kwargs) -> None:
        self.engine = engine or ''
        self.model = model or ''
        if kwargs:
            self.stage_provenance.update(kwargs)

    def record_alias_kind(self, kind: str, count: int = 1) -> None:
        self.alias_kinds[kind] = self.alias_kinds.get(kind, 0) + int(count)

    def mark_blocked(
        self,
        file_path: str,
        translation_id: str,
        reason: str,
        *,
        original_text: str | None = None,
        translated_text: str | None = None,
    ) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        fr.blocked += 1
        rec: Dict[str, Any] = {
            'translation_id': translation_id,
            'status': 'blocked',
            'reason': reason,
        }
        if original_text is not None:
            rec['original_text'] = original_text
        if translated_text is not None:
            rec['translated_text'] = translated_text
        fr.entries.append(rec)
        self.total_blocked_as_corrupted += 1

    def mark_recovered(
        self,
        file_path: str,
        translation_id: str,
        reason: str,
        *,
        original_text: str | None = None,
        translated_text: str | None = None,
    ) -> None:
        fr = self.files.get(file_path)
        if not fr:
            fr = FileReport(file_path=file_path)
            self.files[file_path] = fr
        rec: Dict[str, Any] = {
            'translation_id': translation_id,
            'status': 'recovered',
            'reason': reason,
        }
        if original_text is not None:
            rec['original_text'] = original_text
        if translated_text is not None:
            rec['translated_text'] = translated_text
        fr.entries.append(rec)
        if reason == 'retry':
            fr.recovered_retry += 1
            self.total_recovered_by_retry += 1
        elif reason == 'synthesized_variant':
            fr.recovered_variant += 1
            self.total_recovered_by_synthesized_variant += 1

    def add_coverage_warning(
        self,
        code: str,
        count: int,
        *,
        samples: List[Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        rec: Dict[str, Any] = {
            'code': code,
            'count': int(count),
        }
        if samples:
            rec['samples'] = samples
        if metadata:
            rec['metadata'] = metadata
        self.coverage_warnings.append(rec)

    def to_dict(self) -> Dict[str, Any]:
        return {
            '_notice': 'Developer diagnostic report — intended for developers and bug reports.',
            'project': self.project,
            'target_language': self.target_language,
            'totals': {
                'extracted': self.total_extracted,
                'translated': self.total_translated,
                'written': self.total_written,
                'skipped': self.total_skipped,
                'unchanged': self.total_unchanged,
                'unchanged_by_engine': self.total_unchanged_by_engine,
                'blocked_as_corrupted': self.total_blocked_as_corrupted,
                'recovered_by_retry': self.total_recovered_by_retry,
                'recovered_by_synthesized_variant': self.total_recovered_by_synthesized_variant,
                'coverage_warning_count': len(self.coverage_warnings),
                'normalized_wrapper': self.total_normalized_wrapper,
            },
            'provenance': {
                'engine': self.engine,
                'model': self.model,
                **self.stage_provenance,
            },
            'unchanged_reasons': dict(self.unchanged_reasons),
            'alias_kinds': dict(self.alias_kinds),
            'coverage_warnings': self.coverage_warnings,
            'files': {p: {
                'extracted': fr.extracted,
                'translated': fr.translated,
                'written': fr.written,
                'skipped': fr.skipped,
                'unchanged': fr.unchanged,
                'blocked': fr.blocked,
                'recovered_retry': fr.recovered_retry,
                'recovered_variant': fr.recovered_variant,
                'normalized_wrapper': fr.normalized_wrapper,
                'entries': fr.entries,
            } for p, fr in self.files.items()}
        }

    def write(self, path: str):
        p = Path(path)
        try:
            from src.utils.encoding import save_text_safely
            content = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
            save_text_safely(p, content, encoding='utf-8')
        except Exception:
            logger.warning("Failed to write diagnostics report to %s", path, exc_info=True)
