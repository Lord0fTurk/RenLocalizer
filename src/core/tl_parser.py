# -*- coding: utf-8 -*-
"""
Translation File Parser
=======================

Ren'Py translate dosyalarını (tl/<dil>/*.rpy) parse eder ve çevirir.

İki format desteklenir:
1. Strings format: old "..." / new "..."
2. Dialogue format: # character "orijinal" ve character "" satırları
"""

import os
import re
import logging
import hashlib
import time
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.encoding import read_text_safely, save_text_safely

_UNESCAPE_MAP = {'n': '\n', 't': '\t', '"': '"', "'": "'", '\\': '\\'}
# Ren'Py turns \{ \[ \% into {{ [[ %% (literal brackets/percent); they are
# kept as written so a rewrite reproduces them. Any other unknown escape is
# just the character, as in Ren'Py's lexer.
_KEPT_ESCAPES = '{[%'
_ESCAPE_SEQ_RE = re.compile(r'\\(.)', re.S)


def _unescape_match(m: "re.Match[str]") -> str:
    c = m.group(1)
    if c in _UNESCAPE_MAP:
        return _UNESCAPE_MAP[c]
    return m.group(0) if c in _KEPT_ESCAPES else c


@dataclass
class TranslationEntry:
    """Tek bir çeviri girişi"""
    original_text: str      # Orijinal metin
    translated_text: str    # Çevrilmiş metin (boş olabilir)
    file_path: str
    line_number: int
    entry_type: str         # 'string' veya 'dialogue'
    character: Optional[str] = None  # Karakter adı (dialogue için)
    source_comment: Optional[str] = None  # # game/dosya.rpy:123 gibi
    block_id: Optional[str] = None  # translate block id
    context_path: List[str] = field(default_factory=list)
    translation_id: str = ""
    
    def compute_id(self) -> str:
        if self.translation_id:
            return self.translation_id
        return TLParser.make_translation_id(self.file_path, self.line_number, self.original_text, self.context_path)
    
    def needs_translation(self) -> bool:
        """Çeviri gerekiyor mu?"""
        return not self.translated_text or self.translated_text.strip() == ""

    def is_source_copy(self) -> bool:
        """The 'translation' is just the original text copied over.

        Ren'Py's "Generate Translations" fills every dialogue line and every
        `new` with the source text, so these are untranslated even though
        they are not empty.
        """
        return bool(self.translated_text) and self.translated_text.strip() == (self.original_text or "").strip()

    # Geriye uyumluluk için
    @property
    def old_text(self) -> str:
        return self.original_text
    
    @property
    def new_text(self) -> str:
        return self.translated_text


@dataclass  
class TranslationFile:
    """Bir çeviri dosyasının içeriği"""
    file_path: str
    language: str
    entries: List[TranslationEntry] = field(default_factory=list)
    file_type: str = "mixed"  # 'strings', 'dialogue', 'mixed'
    
    def get_untranslated(self) -> List[TranslationEntry]:
        """Çevrilmemiş girişleri döndürür"""
        return [e for e in self.entries if e.needs_translation()]
    
    def get_translated_count(self) -> int:
        """Çevrilmiş giriş sayısı"""
        return len([e for e in self.entries if not e.needs_translation()])


class TLParser:
    """
    Ren'Py translate dosyalarını parse eder.
    
    İki format desteklenir:
    
    1. Strings format (common.rpy):
        translate turkish strings:
            old "Start"
            new ""
    
    2. Dialogue format (script dosyaları):
        translate turkish label_id:
            # gg "Hello world"
            gg ""
    
    3. Narrator format (karaktersiz):
        translate turkish label_id:
            # "Narrator text here"
            ""
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Regex patterns
        # translate turkish strings: VEYA translate turkish some_label_12ab34cd:
        self._translate_block_re = re.compile(
            r'^translate\s+(\w+)\s+(\w+)\s*:\s*$',
            re.IGNORECASE
        )
        
        # old "..." / new "..." for strings format (supports single and double quotes)
        self._old_re = re.compile(r'^\s*old\s+(?P<quote>["\'])(?P<text>.*)(?P=quote)\s*$')
        self._new_re = re.compile(r'^\s*new\s+(?P<quote>["\'])(?P<text>.*)(?P=quote)\s*$')
        
        # Speaker pattern: bare identifier (with optional dot/attributes) or quoted string
        _speaker_pattern = r'(?P<speaker>[A-Za-z_][\w\.]*(?:\s+[^"\'\n]+)?|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'

        # Clauses Ren'Py allows after the text of a say statement. A menu's
        # caption is stored as 'who "what" nointeract'; without this tail the
        # line was not recognised and its translation was never filled in.
        _say_tail = r'(?P<tail>(?:\s+(?:nointeract|with\s+[^\s(]+(?:\((?:[^()]|\([^()]*\))*\))?|id\s+\w+))*)'

        # # character "text" - dialogue orijinal yorum satırı (karakterli)
        self._dialogue_comment_re = re.compile(rf'^\s*#\s*{_speaker_pattern}\s+(?P<quote>["\'])(?P<text>.*?)(?P=quote){_say_tail}\s*$')

        # # "text" - narrator orijinal yorum satırı (karaktersiz)
        self._narrator_comment_re = re.compile(rf'^\s*#\s*(?P<quote>["\'])(?P<text>(?:(?!(?P=quote)).|\\.)*)(?P=quote){_say_tail}\s*$')

        # character "" veya character "text" - dialogue çeviri satırı
        self._dialogue_line_re = re.compile(rf'^\s*{_speaker_pattern}\s+(?P<quote>["\'])(?P<text>.*?)(?P=quote){_say_tail}\s*$')

        # "" veya "text" - narrator çeviri satırı (karaktersiz)
        self._narrator_line_re = re.compile(rf'^\s*(?P<quote>["\'])(?P<text>(?:(?!(?P=quote)).|\\.)*)(?P=quote){_say_tail}\s*$')
        
        # Sadece # path.rpy:123 veya # game/path.rpy:123 formatı - kaynak yorum
        self._source_comment_re = re.compile(r'^\s*#\s*([^:]+:\d+)\s*$')

        # Custom Context Comment (RenLocalizer Deep Scan & manual)
        # Format: # context: screen:options
        self._context_comment_re = re.compile(r'^\s*#\s*context:\s*(.+)\s*$')
    
    @staticmethod
    def make_translation_id(file_path: str, line_number: int, text: str, context_path: Optional[List[str]] = None, raw_text: Optional[str] = None) -> str:
        """Deterministik ve context-aware translation ID (hash tabanlı).

        Eğer `raw_text` sağlanmışsa ID hesaplamasında raw (kaynak literal)
        kullanılır; aksi halde `text` kullanılır. Satır sonları normalize edilir
        (CRLF -> LF) böylece platform farklılıkları azaltılır.
        """
        ctx = "|".join(context_path or [])

        # Choose the best available text (prefer raw literal when provided)
        source_text = raw_text if (raw_text is not None and raw_text != '') else (text or '')

        # Canonicalize the source text so that minor differences (escaped
        # sequences vs actual newlines, CRLF vs LF, quoting) collapse to the
        # same canonical form used for hashing. This reduces duplicate IDs that
        # arise from escape/newline representation differences.
        try:
            # Strip surrounding quotes if present
            if (source_text.startswith('"') and source_text.endswith('"')) or (source_text.startswith("'") and source_text.endswith("'")):
                source_text = source_text[1:-1]

            # Normalize explicit CRLF/R into LF first
            source_text = source_text.replace('\r\n', '\n').replace('\r', '\n')

            # Try to decode backslash-escaped sequences so that a literal
            # "\\n" becomes an actual newline. Use unicode_escape which
            # handles common C/Python-style escapes. If it fails, fall back
            # to simpler replacements below.
            try:
                # v2.5.1: More robust normalization for ID stability
                source_text = source_text.replace('\\\\', '\\').replace('\\"', '"').replace("\\'", "'")
                source_text = bytes(source_text, 'utf-8').decode('unicode_escape')
            except Exception:
                pass

            # Final pass of common escape replacements to be robust
            source_text = source_text.replace('\\r\\n', '\n').replace('\\r', '\n').replace('\\n', '\n')
            source_text = source_text.replace('\\t', '\t').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
        except Exception:
            # If anything goes wrong, keep original source_text (best-effort)
            pass

        # Ensure line endings are normalized to LF
        source_text = source_text.replace('\r\n', '\n').replace('\r', '\n')

        # Kararlı ID Mantığı (v3):
        # Ren'Py diyalog blokları benzersiz bir ID'ye sahiptir (örn: script_1234abcd).
        # Eğer blok bir ID ise, satır numarasını hash'ten çıkartıyoruz.
        is_stable = ctx and ctx != 'strings' and not ctx.startswith('id_')
        
        if is_stable:
            base = f"{Path(file_path).as_posix()}|{ctx}|{source_text}"
        else:
            base = f"{Path(file_path).as_posix()}|{line_number}|{ctx}|{source_text}"
            
        digest = hashlib.sha1(base.encode('utf-8', errors='ignore')).hexdigest()[:16]
        return f"id_{digest}"
    
    def should_skip_text(self, text: str) -> bool:
        """Boş veya anlamsız metin mi kontrol et"""
        if not text or not text.strip():
            return True
        
        text = text.strip()
        # Ren'Py placeholder'larını (⟦V000⟧ veya ?V000?) atla
        if re.search(r'\?[A-Za-z]\d{3}\?', text):
            return True
        if re.search(r'[\u27e6\u27e7]', text):
            return True
        
        # Çok kısa metinleri atla (tek karakter)
        if len(text) <= 1:
            return True
        
        # Sadece sayı olanları atla
        if text.replace('.', '').replace(',', '').isdigit():
            return True
        
        return False
    
    def parse_file(self, file_path: str) -> Optional[TranslationFile]:
        """
        Tek bir çeviri dosyasını parse eder.
        """
        content = read_text_safely(Path(file_path))
        if content is None:
            self.logger.error(f"Dosya okunamadı: {file_path}")
            return None
        
        lines = content.split('\n')
        
        # Dil kodunu bul
        language = None
        for line in lines:
            match = self._translate_block_re.match(line.strip())
            if match:
                language = match.group(1)
                break
        
        if not language:
            # translate bloğu olmayan dosyaları atla
            return None
        
        tl_file = TranslationFile(
            file_path=file_path,
            language=language
        )
        
        # Parse entries
        entries = self._parse_all_entries(lines, file_path)
        tl_file.entries = entries
        
        # Dosya tipini belirle
        string_count = sum(1 for e in entries if e.entry_type == 'string')
        dialogue_count = sum(1 for e in entries if e.entry_type == 'dialogue')
        
        if string_count > 0 and dialogue_count == 0:
            tl_file.file_type = 'strings'
        elif dialogue_count > 0 and string_count == 0:
            tl_file.file_type = 'dialogue'
        else:
            tl_file.file_type = 'mixed'
        
        self.logger.info(f"Parse edildi: {file_path} - {len(entries)} giriş ({tl_file.file_type})")
        
        return tl_file
    
    def _parse_all_entries(self, lines: List[str], file_path: str) -> List[TranslationEntry]:
        """Tüm çeviri girişlerini parse et - her iki formatı da destekler"""
        entries = []
        
        i = 0
        current_block_id = None
        current_source_comment = None
        in_translate_block = False
        block_type = None  # 'strings' veya 'dialogue'
        
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            ctx = [current_block_id] if current_block_id else []
            
            # Boş satırları atla
            if not stripped:
                i += 1
                continue
            
            # translate block başlangıcı
            block_match = self._translate_block_re.match(stripped)
            if block_match:
                current_block_id = block_match.group(2)
                in_translate_block = True
                
                if current_block_id == 'strings':
                    block_type = 'strings'
                else:
                    block_type = 'dialogue'
                
                i += 1
                continue
            
            # Source comment (# game/path.rpy:123)
            source_match = self._source_comment_re.match(stripped)
            if source_match:
                current_source_comment = source_match.group(1)
                i += 1
                continue
            
            # Context comment (# context: screen:x)
            ctx_match = self._context_comment_re.match(stripped)
            if ctx_match:
                # Add to current context for the next entry
                # We store it transiently.
                # Note: This implementation assumes context comment comes immediately before the entry
                # or inside the block.
                extra_ctx = ctx_match.group(1).strip()
                # If we are in a block, we can't easily append to current_block_id (it's a string)
                # But we can use it when creating the Entry.
                # Let's verify if we need a list for current_context
                # For now, let's just append it to a temporary list
                if not hasattr(self, '_temp_context_list'):
                     self._temp_context_list = []
                self._temp_context_list.append(extra_ctx)
                i += 1
                continue
            
            # STRINGS FORMAT: old "..." / new "..."
            old_match = self._old_re.match(stripped)
            if old_match:
                old_text = self._unescape_string(old_match.group('text'))
                new_text = ""
                line_no = i + 1
                
                # Combine block ID and temp context
                final_ctx = []
                if current_block_id: final_ctx.append(current_block_id)
                if hasattr(self, '_temp_context_list') and self._temp_context_list:
                    final_ctx.extend(self._temp_context_list)
                    self._temp_context_list = [] # Reset after consuming

                
                # Sonraki satır new "..." olmalı
                if i + 1 < len(lines):
                    next_stripped = lines[i + 1].strip()
                    new_match = self._new_re.match(next_stripped)
                    if new_match:
                        new_text = self._unescape_string(new_match.group('text'))
                        i += 1
                
                if not self.should_skip_text(old_text):
                    entry = TranslationEntry(
                        original_text=old_text,
                        translated_text=new_text,
                        file_path=file_path,
                        line_number=line_no,
                        entry_type='string',
                        source_comment=current_source_comment,
                        block_id=current_block_id,
                        context_path=final_ctx,
                        translation_id=self.make_translation_id(file_path, line_no, old_text, final_ctx)
                    )
                    entries.append(entry)
                
                current_source_comment = None
                i += 1
                continue
            
            # DIALOGUE FORMAT: # character "text" yorumu ve karakter "" satırı
            if in_translate_block and block_type == 'dialogue':
                # Önce karakterli diyalog kontrol et (# gg "Hello")
                comment_match = self._dialogue_comment_re.match(stripped)
                if comment_match:
                    character = comment_match.group('speaker')
                    original_text = self._unescape_string(comment_match.group('text'))
                    ctx = [current_block_id] if current_block_id else []
                    
                    # Sonraki satırda karakter "" olmalı
                    if i + 1 < len(lines):
                        next_stripped = lines[i + 1].strip()
                        dialogue_match = self._dialogue_line_re.match(next_stripped)
                        
                        if dialogue_match:
                            char_name = dialogue_match.group('speaker')
                            translated_text = self._unescape_string(dialogue_match.group('text'))
                            
                            if not self.should_skip_text(original_text):
                                entry = TranslationEntry(
                                    original_text=original_text,
                                    translated_text=translated_text,
                                    file_path=file_path,
                                    line_number=i + 2,  # dialogue satırının numarası
                                    entry_type='dialogue',
                                    character=char_name,
                                    source_comment=current_source_comment,
                                    block_id=current_block_id,
                                    context_path=[current_block_id] if current_block_id else [],
                                    translation_id=self.make_translation_id(file_path, i + 2, original_text, [current_block_id] if current_block_id else [])
                                )
                                entries.append(entry)
                            
                            i += 2
                            current_source_comment = None
                            continue
                
                # Narrator formatı kontrol et (# "Hello" - karaktersiz)
                narrator_match = self._narrator_comment_re.match(stripped)
                if narrator_match:
                    original_text = self._unescape_string(narrator_match.group('text'))
                    ctx = [current_block_id] if current_block_id else []
                    
                    # Sonraki satırda "" olmalı
                    if i + 1 < len(lines):
                        next_stripped = lines[i + 1].strip()
                        narrator_line_match = self._narrator_line_re.match(next_stripped)
                        
                        if narrator_line_match:
                            translated_text = self._unescape_string(narrator_line_match.group('text'))
                            
                            if not self.should_skip_text(original_text):
                                entry = TranslationEntry(
                                    original_text=original_text,
                                    translated_text=translated_text,
                                    file_path=file_path,
                                    line_number=i + 2,
                                    entry_type='narrator',
                                    character=None,
                                    source_comment=current_source_comment,
                                    block_id=current_block_id,
                                    context_path=[current_block_id] if current_block_id else [],
                                    translation_id=self.make_translation_id(file_path, i + 2, original_text, [current_block_id] if current_block_id else [])
                                )
                                entries.append(entry)
                            
                            i += 2
                            current_source_comment = None
                            continue
                
                i += 1
                continue
            
            # Block dışına çıkış kontrolü (indent azalması)
            if in_translate_block and stripped and not stripped.startswith('#'):
                if not line.startswith('    ') and not line.startswith('\t'):
                    if not self._translate_block_re.match(stripped):
                        in_translate_block = False
                        block_type = None
                        current_block_id = None
            
            i += 1
        
        return entries
    
    def _unescape_string(self, text: str) -> str:
        """Ren'Py string escape'lerini geri çevir.

        Tek geçiş: zincirleme replace "\\\\n" (ters bölü + n) dizisini satır
        sonuna çeviriyordu. \\{ \\[ \\% olduğu gibi kalır (_escape_string
        bunları ikilemez); diğer bilinmeyen kaçışlar Ren'Py'daki gibi karakterin
        kendisidir.
        """
        if not text:
            return text
        return _ESCAPE_SEQ_RE.sub(_unescape_match, text)

    def _escape_string(self, text: str) -> str:
        """Ren'Py için string escape et (_unescape_string'in tersi)."""
        if not text:
            return text

        out = []
        n = len(text)
        for i, ch in enumerate(text):
            if ch == '\\':
                nxt = text[i + 1] if i + 1 < n else ''
                # A backslash kept from \{ \[ \% stays single; any other
                # backslash is a literal one ("¯\\_(ツ)_/¯") and is doubled.
                out.append('\\' if nxt and nxt in _KEPT_ESCAPES else '\\\\')
            elif ch == '"':
                out.append('\\"')
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\t':
                out.append('\\t')
            else:
                out.append(ch)
        return ''.join(out)
    
    def parse_directory(self, tl_dir: str, language: str) -> List[TranslationFile]:
        """
        tl/<dil>/ klasöründeki tüm .rpy dosyalarını parse eder.
        
        Args:
            tl_dir: tl klasörü yolu (game/tl)
            language: Dil kodu (turkish, spanish, vs.)
            
        Returns:
            TranslationFile listesi
        """
        lang_dir = os.path.join(tl_dir, language)

        # Guard: eğer tl_dir zaten language adıyla bitiyorsa çift join yapma
        # (örn. tl_dir="game/tl/turkish", language="turkish" → yanlış "game/tl/turkish/turkish")
        tl_dir_basename = os.path.basename(os.path.normpath(tl_dir))
        if tl_dir_basename.lower() == language.lower() and os.path.isdir(tl_dir):
            lang_dir = tl_dir
        
        # Case-insensitive folder search fallback for Linux/Mac
        if not os.path.isdir(lang_dir) and os.path.isdir(tl_dir):
            try:
                available_dirs = [d for d in os.listdir(tl_dir) if os.path.isdir(os.path.join(tl_dir, d))]
                for d in available_dirs:
                    if d.lower() == language.lower():
                        lang_dir = os.path.join(tl_dir, d)
                        self.logger.info(f" Case-insensitive match found: {language} -> {d}")
                        break
            except Exception as e:
                self.logger.warning(f"Directory listing failed: {e}")

        if not os.path.isdir(lang_dir):
            self.logger.warning(f"Dil klasörü bulunamadı: {lang_dir}")
            return []
        
        files = []
        
        for i, (root, dirs, filenames) in enumerate(os.walk(lang_dir)):
            # GÜVENLİK: 'renpy' adlı klasörleri tamamen atla (içine girme)
            # Linux ve Mac'te olası farklı isimleri de düşünerek lower() kontrolü ekliyoruz
            dirs[:] = [d for d in dirs if d.lower() != 'renpy']
            
            for filename in filenames:
                if filename.lower().endswith('.rpy'):
                    file_path = os.path.join(root, filename)
                    tl_file = self.parse_file(file_path)
                    if tl_file:
                        files.append(tl_file)
            
            # Yield every few directories/files
            if i % 10 == 0:
                time.sleep(0.001)
        
        self.logger.info(f"Toplam {len(files)} dosya parse edildi: {lang_dir}")
        
        return files
    
    @staticmethod
    def _pick_translation(translations: Dict[str, str], translation_id: str,
                          original: str, existing: str) -> Optional[str]:
        """New text for one slot, or None to keep what is there.

        A text-keyed translation only fills a slot that is empty or still a
        copy of the source; otherwise a line the user already translated by
        hand was overwritten whenever the same sentence was translated
        somewhere else.
        """
        by_id = translations.get(translation_id)
        if by_id:
            return by_id
        if not existing or not existing.strip() or existing.strip() == (original or '').strip():
            return translations.get(original)
        return None

    def update_translations(
        self,
        tl_file: TranslationFile,
        translations: Dict[str, str]
    ) -> str:
        """
        Çevirileri dosya içeriğine uygular ve yeni içeriği döndürür.
        Her iki formatı da destekler: strings (old/new) ve dialogue (# comment / character "")
        """
        content = read_text_safely(Path(tl_file.file_path))
        if content is None:
            raise IOError(f"Dosya okunamadı: {tl_file.file_path}")
        
        lines = content.split('\n')
        new_lines = []
        
        current_block_id: Optional[str] = None
        block_type: Optional[str] = None  # strings | dialogue
        in_translate_block = False
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            ctx = [current_block_id] if current_block_id else []

            block_match = self._translate_block_re.match(stripped)
            if block_match:
                current_block_id = block_match.group(2)
                in_translate_block = True
                block_type = 'strings' if current_block_id == 'strings' else 'dialogue'
                new_lines.append(line)
                i += 1
                continue
            
            # STRINGS FORMAT: old "..." / new "..."
            old_match = self._old_re.match(stripped)
            if old_match:
                old_text = self._unescape_string(old_match.group('text'))
                new_lines.append(line)  # old satırını ekle
                translation_id = self.make_translation_id(tl_file.file_path, i + 1, old_text, ctx)
                
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_stripped = next_line.strip()
                    new_match = self._new_re.match(next_stripped)
                    
                    if new_match:
                        existing_translated = self._unescape_string(new_match.group('text'))
                        translated = self._pick_translation(translations, translation_id, old_text, existing_translated)
                        if translated is None:
                            translated = existing_translated
                        escaped = self._escape_string(translated or "")
                        indent = len(next_line) - len(next_line.lstrip())
                        new_lines.append(' ' * indent + f'new "{escaped}"')
                        
                        i += 2
                        continue
                
                i += 1
                continue
            
            # DIALOGUE FORMAT: # character "text" ve karakter ""
            if in_translate_block and block_type == 'dialogue':
                comment_match = self._dialogue_comment_re.match(stripped)
                if comment_match and i + 1 < len(lines):
                    original_text = self._unescape_string(comment_match.group('text'))
                    new_lines.append(line)  # yorum satırını ekle
                    translation_id = self.make_translation_id(tl_file.file_path, i + 2, original_text, ctx)

                    next_line = lines[i + 1]
                    next_stripped = next_line.strip()
                    dialogue_match = self._dialogue_line_re.match(next_stripped)
                    
                    if dialogue_match:
                        char_name = dialogue_match.group('speaker')
                        existing_translated = self._unescape_string(dialogue_match.group('text'))
                        translated = self._pick_translation(translations, translation_id, original_text, existing_translated)
                        if translated is None:
                            translated = existing_translated
                        escaped = self._escape_string(translated or "")
                        indent = len(next_line) - len(next_line.lstrip())
                        new_lines.append(' ' * indent + f'{char_name} "{escaped}"' + (dialogue_match.group('tail') or ''))
                    
                    i += 2
                    continue
                
                # Narrator format: # "text" ve ""
                narrator_match = self._narrator_comment_re.match(stripped)
                if narrator_match and i + 1 < len(lines):
                    original_text = self._unescape_string(narrator_match.group('text'))
                    new_lines.append(line)  # yorum satırını ekle
                    translation_id = self.make_translation_id(tl_file.file_path, i + 2, original_text, ctx)
                    
                    next_line = lines[i + 1]
                    next_stripped = next_line.strip()
                    narrator_line_match = self._narrator_line_re.match(next_stripped)
                    
                    if narrator_line_match:
                        existing_translated = self._unescape_string(narrator_line_match.group('text'))
                        translated = self._pick_translation(translations, translation_id, original_text, existing_translated)
                        if translated is None:
                            translated = existing_translated
                        escaped = self._escape_string(translated or "")
                        indent = len(next_line) - len(next_line.lstrip())
                        new_lines.append(' ' * indent + f'"{escaped}"' + (narrator_line_match.group('tail') or ''))
                    
                    i += 2
                    continue
            
            # Block dışına çıkma kontrolü (indent azaltması)
            if in_translate_block and stripped and not stripped.startswith('#'):
                if not line.startswith('    ') and not line.startswith('\t'):
                    if not self._translate_block_re.match(stripped):
                        in_translate_block = False
                        block_type = None
                        current_block_id = None
            
            new_lines.append(line)
            i += 1
        
        return '\n'.join(new_lines)
    
    def apply_line_edits(self, content: str, edits: List[Dict]) -> Tuple[str, List[int]]:
        """Replace single translation lines in *content*; return (content, failed lines).

        Each edit is ``{"line", "kind", "original", "text"}`` where ``line`` and
        ``kind`` are the ``line_number``/``entry_type`` that ``parse_file``
        reported. The line is rewritten only when the source line above it
        still carries ``original``; anything else (the file was regenerated,
        lines moved) is reported as failed instead of writing to the wrong
        slot. Speaker, indentation, the say tail and line endings are kept.
        """
        lines = content.split('\n')
        failed: List[int] = []
        for edit in edits:
            ln = int(edit["line"])
            kind = edit["kind"]
            if kind == 'string':
                src_idx, dst_idx, src_re, dst_re = ln - 1, ln, self._old_re, self._new_re
            elif kind == 'dialogue':
                src_idx, dst_idx, src_re, dst_re = ln - 2, ln - 1, self._dialogue_comment_re, self._dialogue_line_re
            else:
                src_idx, dst_idx, src_re, dst_re = ln - 2, ln - 1, self._narrator_comment_re, self._narrator_line_re
            if src_idx < 0 or dst_idx >= len(lines):
                failed.append(ln)
                continue
            src_match = src_re.match(lines[src_idx].strip())
            dst_line = lines[dst_idx]
            eol = '\r' if dst_line.endswith('\r') else ''
            body = dst_line[:-1] if eol else dst_line
            dst_match = dst_re.match(body.strip())
            if (not src_match or not dst_match
                    or self._unescape_string(src_match.group('text')) != edit["original"]):
                failed.append(ln)
                continue
            indent = body[:len(body) - len(body.lstrip())]
            escaped = self._escape_string(edit["text"] or "")
            if kind == 'string':
                new_body = f'new "{escaped}"'
            elif kind == 'dialogue':
                new_body = f'{dst_match.group("speaker")} "{escaped}"{dst_match.group("tail") or ""}'
            else:
                new_body = f'"{escaped}"{dst_match.group("tail") or ""}'
            lines[dst_idx] = indent + new_body + eol
        return '\n'.join(lines), failed

    def save_translations(
        self,
        tl_file: TranslationFile,
        translations: Dict[str, str],
        output_path: Optional[str] = None
    ) -> bool:
        """
        Çevirileri dosyaya kaydeder.
        """
        try:
            updated_content = self.update_translations(tl_file, translations)
            
            save_path = output_path or tl_file.file_path
            
            success = save_text_safely(Path(save_path), updated_content, encoding='utf-8-sig', newline='\n')
            
            if success:
                self.logger.info(f"Kaydedildi: {save_path}")
            else:
                self.logger.warning(f"Kaydetme başarısız: {save_path}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Kaydetme hatası: {e}")
            return False


def get_translation_stats(tl_files: List[TranslationFile]) -> Dict:
    """Çeviri istatistikleri"""
    total_entries = 0
    translated_entries = 0
    untranslated_entries = 0
    
    for tl_file in tl_files:
        for entry in tl_file.entries:
            total_entries += 1
            if entry.needs_translation():
                untranslated_entries += 1
            else:
                translated_entries += 1
    
    return {
        'total': total_entries,
        'translated': translated_entries,
        'untranslated': untranslated_entries,
        'progress': (translated_entries / total_entries * 100) if total_entries > 0 else 0
    }
