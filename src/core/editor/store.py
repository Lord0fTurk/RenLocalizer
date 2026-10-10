# -*- coding: utf-8 -*-
"""In-memory SQLite store behind the translation editor.

The tl/<lang>/*.rpy files are the source of truth; this store is rebuilt
from them on every load (20k lines parse in under two seconds), so there is
no on-disk database that can go stale. Search is a diacritic- and
case-insensitive substring match on a pre-folded column.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.editor.checks import _TOKEN_RE, find_problem, translation_status

STATUS_FILTERS = ("all", "untranslated", "translated", "modified", "warnings")
KIND_FILTERS = ("all", "dialogue", "string")

_COLUMNS = (
    "id, file_path, file_rel, line, kind, block_id, speaker, speaker_name, source_ref, "
    "original, translated, saved, status, problem, modified, seq"
)


def fold(text: str) -> str:
    """Case- and diacritic-insensitive form used for searching (ı/İ fold to i)."""
    text = (text or "").replace("İ", "i").replace("I", "i").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text.replace("ı", "i")


def _search_blob(original: str, text: str, speaker: str) -> str:
    return fold("\n".join((original, text, speaker)))


class EditorStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_rel TEXT NOT NULL,
                line INTEGER NOT NULL,
                kind TEXT NOT NULL,
                block_id TEXT DEFAULT '',
                speaker TEXT DEFAULT '',
                speaker_name TEXT DEFAULT '',
                source_ref TEXT DEFAULT '',
                original TEXT NOT NULL,
                translated TEXT NOT NULL,
                saved TEXT NOT NULL,
                status TEXT NOT NULL,
                problem TEXT DEFAULT '',
                modified INTEGER DEFAULT 0,
                seq INTEGER NOT NULL,
                search TEXT NOT NULL
            );
            CREATE INDEX idx_file ON entries(file_rel);
            CREATE INDEX idx_status ON entries(status);
            CREATE INDEX idx_modified ON entries(modified);
            """
        )

    def close(self) -> None:
        with self._lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    # ── Loading ─────────────────────────────────────────────────────────

    def load(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Replace all entries. Unsaved edits of the same slot are carried over."""
        with self._lock:
            pending = {
                (r["file_path"], r["line"], r["original"]): r["translated"]
                for r in self.conn.execute(
                    "SELECT file_path, line, original, translated FROM entries WHERE modified = 1")
            }
            self.conn.execute("DELETE FROM entries")
            records = []
            for seq, r in enumerate(rows):
                saved = r.get("translated") or ""
                text = pending.get((r["file_path"], int(r["line"]), r["original"]), saved)
                records.append(self._record(seq, r, text, saved))
            self.conn.executemany(
                "INSERT INTO entries (file_path, file_rel, line, kind, block_id, speaker, speaker_name, "
                "source_ref, original, translated, saved, status, problem, modified, seq, search) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                records,
            )
            self.conn.commit()
            return len(records)

    @staticmethod
    def _record(seq: int, r: Dict[str, Any], text: str, saved: str) -> tuple:
        original = r["original"]
        speaker_name = r.get("speaker_name") or r.get("speaker") or ""
        return (
            r["file_path"], r.get("file_rel") or r["file_path"], int(r["line"]), r["kind"],
            r.get("block_id") or "", r.get("speaker") or "", r.get("speaker_name") or "",
            r.get("source_ref") or "", original, text, saved,
            translation_status(original, text), find_problem(original, text) or "",
            1 if text != saved else 0, seq, _search_blob(original, text, speaker_name),
        )

    # ── Queries ─────────────────────────────────────────────────────────

    @staticmethod
    def _where(search: str = "", file_rel: str = "all", kind: str = "all",
               status: str = "all") -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if search and search.strip():
            clauses.append("instr(search, ?) > 0")
            params.append(fold(search.strip()))
        if file_rel and file_rel != "all":
            clauses.append("file_rel = ?")
            params.append(file_rel)
        if kind == "dialogue":
            clauses.append("kind != 'string'")
        elif kind == "string":
            clauses.append("kind = 'string'")
        if status == "untranslated":
            clauses.append("status != 'translated'")
        elif status == "translated":
            clauses.append("status = 'translated'")
        elif status == "modified":
            clauses.append("modified = 1")
        elif status == "warnings":
            clauses.append("problem != ''")
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def query(self, search: str = "", file_rel: str = "all", kind: str = "all", status: str = "all",
              page: int = 1, page_size: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        where, params = self._where(search, file_rel, kind, status)
        with self._lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM entries {where}", params).fetchone()[0]
            offset = (max(1, page) - 1) * page_size
            rows = self.conn.execute(
                f"SELECT {_COLUMNS} FROM entries {where} ORDER BY seq LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def get(self, entry_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(f"SELECT {_COLUMNS} FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def neighbors(self, entry_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Previous and next line of the same file (dialogue context)."""
        row = self.get(entry_id)
        if not row:
            return None, None
        with self._lock:
            prev = self.conn.execute(
                f"SELECT {_COLUMNS} FROM entries WHERE file_path = ? AND seq < ? ORDER BY seq DESC LIMIT 1",
                (row["file_path"], row["seq"])).fetchone()
            nxt = self.conn.execute(
                f"SELECT {_COLUMNS} FROM entries WHERE file_path = ? AND seq > ? ORDER BY seq LIMIT 1",
                (row["file_path"], row["seq"])).fetchone()
        return (dict(prev) if prev else None), (dict(nxt) if nxt else None)

    def files(self) -> List[str]:
        with self._lock:
            return [r[0] for r in self.conn.execute("SELECT DISTINCT file_rel FROM entries ORDER BY file_rel")]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*), SUM(status = 'empty'), SUM(status = 'source_copy'), "
                "SUM(modified = 1), SUM(problem != '') FROM entries"
            ).fetchone()
        return {
            "total": row[0] or 0,
            "empty": row[1] or 0,
            "source_copy": row[2] or 0,
            "modified": row[3] or 0,
            "warnings": row[4] or 0,
        }

    # ── Editing ─────────────────────────────────────────────────────────

    def _set_text(self, entry_id: int, text: str) -> None:
        row = self.conn.execute(
            "SELECT original, saved, speaker, speaker_name FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return
        original = row["original"]
        self.conn.execute(
            "UPDATE entries SET translated = ?, status = ?, problem = ?, modified = ?, search = ? WHERE id = ?",
            (
                text, translation_status(original, text), find_problem(original, text) or "",
                1 if text != row["saved"] else 0,
                _search_blob(original, text, row["speaker_name"] or row["speaker"] or ""),
                entry_id,
            ),
        )

    def update(self, entry_id: int, text: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._set_text(entry_id, text)
            self.conn.commit()
        return self.get(entry_id)

    def revert(self, entry_id: int) -> Optional[Dict[str, Any]]:
        row = self.get(entry_id)
        return self.update(entry_id, row["saved"]) if row else None

    def replace_all(self, find: str, replace: str, match_case: bool = False, search: str = "",
                    file_rel: str = "all", kind: str = "all", status: str = "all") -> int:
        """Replace *find* in translations within the filter, never inside tags or [variables]."""
        if not find:
            return 0
        pattern = re.compile(re.escape(find), 0 if match_case else re.IGNORECASE)
        where, params = self._where(search, file_rel, kind, status)
        count = 0
        with self._lock:
            for row in self.conn.execute(f"SELECT id, translated FROM entries {where}", params).fetchall():
                new = _replace_outside_tokens(row["translated"], pattern, replace)
                if new != row["translated"]:
                    self._set_text(row["id"], new)
                    count += 1
            self.conn.commit()
        return count

    def modified_by_file(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        with self._lock:
            for row in self.conn.execute(f"SELECT {_COLUMNS} FROM entries WHERE modified = 1 ORDER BY seq"):
                out.setdefault(row["file_path"], []).append(dict(row))
        return out

    def mark_saved(self, entry_ids: Iterable[int]) -> None:
        with self._lock:
            self.conn.executemany(
                "UPDATE entries SET saved = translated, modified = 0 WHERE id = ?",
                [(i,) for i in entry_ids],
            )
            self.conn.commit()


def _replace_outside_tokens(text: str, pattern: "re.Pattern[str]", replace: str) -> str:
    parts: List[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        parts.append(pattern.sub(lambda _m: replace, text[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(pattern.sub(lambda _m: replace, text[pos:]))
    return "".join(parts)
