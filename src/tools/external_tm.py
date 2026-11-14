# -*- coding: utf-8 -*-
"""
External Translation Memory (TM) Module
========================================

Harici Ren'Py projelerinin tl/ klasörlerinden çeviri belleği oluşturur.
Oluşturulan TM, başka oyunların çeviri sürecinde exact match ile
API çağrısı yapmadan çeviri sağlar.

Kullanım:
    1. Tools sayfasından harici bir tl/<dil>/ klasörü seç
    2. TLParser ile parse et → original/translated çiftlerini çıkar
    3. JSON dosyası olarak tm/ klasörüne kaydet
    4. Pipeline çevirisi sırasında exact match lookup yap

Depolama: tm/<kaynak_adı>_<dil>.json
Format:
    {
        "meta": {
            "source_name": "OyunA",
            "language": "turkish",
            "entry_count": 12430,
            "created": "2026-03-08T...",
            "source_path": "/path/to/game/tl/turkish"
        },
        "entries": {
            "Hello": "Merhaba",
            "Save": "Kaydet",
            ...
        }
    }
"""

import os
import re
import json
import logging
import tempfile
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Sabitler ──
MAX_TM_ENTRIES = 100_000  # Tek bir TM dosyası için hard limit
MIN_TEXT_LENGTH = 2       # Minimum metin uzunluğu (1 karakterlik stringler anlamsız)
MAX_TEXT_LENGTH = 5000    # Makine çevirisi için makul üst sınır

# Çevrilmemesi gereken teknik pattern'ler (output_formatter ile uyumlu)
# NOT: re.IGNORECASE kullanılMIYOR — ^[A-Z_]{2,}$ yalnızca ALL_CAPS eşleşmeli,
# aksi halde "Save", "Load", "Continue" gibi meşru çeviriler de filtrelenir.
_TECHNICAL_SKIP_RE = re.compile(
    r'^[\s\d\W]+$'                   # Sadece sayı/sembol
    r'|^[A-Z_]{2,}$'                # ALL_CAPS identifier (case-sensitive)
    r'|^\w+\.\w+\.\w+'              # dotted.path.identifier
    r'|^https?://'                   # URL
    r'|\.(?:rpy|rpyc|png|jpe?g|gif|webp|bmp|ico'  # Görsel uzantıları
    r'|ogg|mp3|wav|flac|aac|m4a'                    # Ses uzantıları
    r'|mp4|webm|avi|mkv|mov'                        # Video uzantıları
    r'|ttf|otf|json|yaml|py)$'                      # Diğer teknik uzantılar
    r'|^[\w\-. ]+(?:/[\w\-. ]+)+$'                  # Slash içeren dosya yolları (images/bg/park.png)
)


@dataclass
class TMImportResult:
    """TM import işleminin sonuçları."""
    source_name: str
    language: str
    total_parsed: int = 0       # Parse edilen toplam entry sayısı
    imported: int = 0           # TM'ye eklenen entry sayısı
    skipped_empty: int = 0      # Çevirisiz atlanalar
    skipped_same: int = 0       # original == translated olanlar
    skipped_technical: int = 0  # Teknik string atlananlar
    skipped_short: int = 0      # Çok kısa atlananlar
    skipped_duplicate: int = 0  # Zaten mevcut olanlar
    output_path: str = ""       # Kaydedilen JSON dosya yolu
    error: str = ""             # Hata mesajı (varsa)
    
    @property
    def success(self) -> bool:
        return self.imported > 0 and not self.error


@dataclass
class TMSource:
    """Bir TM kaynağının metadata'sı."""
    name: str
    language: str
    entry_count: int
    file_path: str
    created: str = ""
    source_path: str = ""
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "language": self.language,
            "entry_count": self.entry_count,
            "file_path": self.file_path,
            "created": self.created,
            "source_path": self.source_path,
        }


class ExternalTMStore:
    """
    External Translation Memory deposu.
    
    Harici projelerden çeviri çiftleri alır, JSON olarak saklar,
    pipeline sırasında exact match lookup sağlar.
    
    Kullanım:
        store = ExternalTMStore(tm_dir="tm")
        
        # Import
        result = store.import_from_tl_directory("/path/to/game/tl/turkish", "OyunA", "turkish")
        
        # Lookup (pipeline sırasında)
        store.load_sources(["tm/OyunA_turkish.json", "tm/OyunB_turkish.json"])
        translation = store.get_exact("Hello")  # → "Merhaba" veya None
    """
    
    def __init__(self, tm_dir: str = "tm"):
        """
        Args:
            tm_dir: TM dosyalarının saklanacağı dizin.
                    Mutlak yol değilse, program köküne göre çözümlenir.
        """
        if os.path.isabs(tm_dir):
            self.tm_dir = tm_dir
        else:
            # Fallback to program root if not absolute
            self._app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.tm_dir = os.path.join(self._app_dir, tm_dir)
        
        # Base directory for relative lookups (usually parent of tm_dir)
        self.base_dir = os.path.dirname(self.tm_dir)
        
        # Aktif TM verileri: {original_text: translated_text}
        self._entries: Dict[str, str] = {}
        
        # Yüklü kaynakların listesi
        self._loaded_sources: List[str] = []
        
        # İstatistikler
        self._lookup_hits: int = 0
        self._lookup_misses: int = 0
        
        # Thread safety
        self._lock = threading.Lock()
    
    # ═══════════════════════════════════════════════════════════════════
    # IMPORT — tl/ klasöründen TM oluştur
    # ═══════════════════════════════════════════════════════════════════
    
    def import_from_tl_directory(
        self, 
        tl_lang_dir: str, 
        source_name: str, 
        language: str,
        progress_callback=None
    ) -> TMImportResult:
        """
        Bir Ren'Py projesinin tl/<dil>/ klasöründen TM oluşturur.
        
        Args:
            tl_lang_dir: tl/<dil> klasör yolu (örn: /path/to/game/tl/turkish)
            source_name: Kaynak adı (örn: "OyunA", "SpaceJourney")
            language: Dil kodu (örn: "turkish", "spanish")
            progress_callback: İlerleme callback'i — fn(current, total, message)
            
        Returns:
            TMImportResult
        """
        result = TMImportResult(source_name=source_name, language=language)
        
        if not os.path.isdir(tl_lang_dir):
            result.error = f"Klasör bulunamadı: {tl_lang_dir}"
            logger.error(result.error)
            return result
        
        # TLParser ile parse et
        try:
            from src.core.tl_parser import TLParser
            parser = TLParser()
            
            # tl_lang_dir zaten tl/<dil> yolu — parent'ını tl_dir olarak kullan
            tl_dir = os.path.dirname(tl_lang_dir)
            lang_folder = os.path.basename(tl_lang_dir)
            
            tl_files = parser.parse_directory(tl_dir, lang_folder)
            
            if not tl_files:
                result.error = f"Hiçbir .rpy dosyası bulunamadı: {tl_lang_dir}"
                logger.warning(result.error)
                return result
                
        except Exception as e:
            result.error = f"Parse hatası: {e}"
            logger.exception(result.error)
            return result
        
        # Entry'leri çıkar ve filtrele
        entries: Dict[str, str] = {}
        total_entries = sum(len(f.entries) for f in tl_files)
        processed = 0
        
        for tl_file in tl_files:
            for entry in tl_file.entries:
                processed += 1
                result.total_parsed += 1
                
                original = (entry.original_text or "").strip()
                translated = (entry.translated_text or "").strip()
                
                # Filtreler
                if not translated:
                    result.skipped_empty += 1
                    continue
                
                if original == translated:
                    result.skipped_same += 1
                    continue
                
                if len(original) < MIN_TEXT_LENGTH or len(translated) < MIN_TEXT_LENGTH:
                    result.skipped_short += 1
                    continue
                
                if len(original) > MAX_TEXT_LENGTH:
                    result.skipped_technical += 1
                    continue
                
                if _TECHNICAL_SKIP_RE.search(original):
                    result.skipped_technical += 1
                    continue
                
                if original in entries:
                    result.skipped_duplicate += 1
                    continue
                
                # Hard limit kontrolü
                if len(entries) >= MAX_TM_ENTRIES:
                    logger.warning(f"TM entry limiti aşıldı ({MAX_TM_ENTRIES}), import durduruluyor")
                    break
                
                entries[original] = translated
                result.imported += 1
                
                # Progress callback
                if progress_callback and processed % 500 == 0:
                    try:
                        progress_callback(processed, total_entries, f"İşleniyor: {processed}/{total_entries}")
                    except Exception:
                        pass
        
        if not entries:
            result.error = "Hiçbir geçerli çeviri çifti bulunamadı"
            return result
        
        # JSON olarak kaydet
        try:
            os.makedirs(self.tm_dir, exist_ok=True)
            
            # Dosya adı: <kaynak_adı>_<dil>.json
            safe_name = re.sub(r'[^\w\-]', '_', source_name)
            safe_lang = re.sub(r'[^\w\-]', '_', language)
            filename = f"{safe_name}_{safe_lang}.json"
            output_path = os.path.join(self.tm_dir, filename)
            
            tm_data = {
                "meta": {
                    "source_name": source_name,
                    "language": language,
                    "entry_count": len(entries),
                    "created": datetime.now().isoformat(),
                    "source_path": tl_lang_dir,
                    "version": "1.0"
                },
                "entries": entries
            }
            
            # Atomic write: temp dosyaya yaz, sonra rename (corruption koruması)
            fd, tmp_path = tempfile.mkstemp(dir=self.tm_dir, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(tm_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, output_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            result.output_path = output_path
            logger.info(
                f"TM kaydedildi: {output_path} "
                f"({result.imported} entry, {result.skipped_empty} boş, "
                f"{result.skipped_same} aynı, {result.skipped_technical} teknik atlandı)"
            )
            
        except Exception as e:
            result.error = f"Kaydetme hatası: {e}"
            logger.exception(result.error)
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # LOAD — TM kaynaklarını belleğe yükle
    # ═══════════════════════════════════════════════════════════════════
    
    def load_sources(self, source_paths: List[str]) -> int:
        """
        Seçili TM kaynakklarını belleğe yükler.
        Önceki yüklemeleri temizler.
        
        Args:
            source_paths: TM JSON dosya yolları listesi
            
        Returns:
            Toplam yüklenen entry sayısı
        """
        with self._lock:
            self._entries.clear()
            self._loaded_sources.clear()
            self._lookup_hits = 0
            self._lookup_misses = 0
        
        for path in source_paths:
            # Göreceli yolları mutlak yola çevir
            if not os.path.isabs(path):
                path = os.path.join(self.base_dir, path)
            
            if not os.path.isfile(path):
                logger.warning(f"TM dosyası bulunamadı: {path}")
                continue
            
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                entries = data.get("entries", {})
                if not isinstance(entries, dict):
                    logger.warning(f"Geçersiz TM formatı: {path}")
                    continue
                
                # Mevcut entries'e ekle (son eklenen kazanır — LIFO)
                loaded_count = 0
                with self._lock:
                    for original, translated in entries.items():
                        if original and translated and original != translated:
                            self._entries[original] = translated
                            loaded_count += 1
                    
                    self._loaded_sources.append(path)
                meta = data.get("meta", {})
                source_name = meta.get("source_name", os.path.basename(path))
                logger.info(f"TM yüklendi: {source_name} ({loaded_count} entry) — {path}")
                
            except json.JSONDecodeError as e:
                logger.error(f"TM JSON parse hatası: {path} — {e}")
            except Exception as e:
                logger.error(f"TM yükleme hatası: {path} — {e}")
        
        total = len(self._entries)
        logger.info(f"Toplam TM: {total} entry ({len(self._loaded_sources)} kaynak)")
        return total
    
    # ═══════════════════════════════════════════════════════════════════
    # LOOKUP — Pipeline sırasında çeviri ara
    # ═══════════════════════════════════════════════════════════════════
    
    def get_exact(self, text: str) -> Optional[str]:
        """
        Exact match lookup. O(1) dict lookup.
        
        Args:
            text: Orijinal metin
            
        Returns:
            Çeviri veya None
        """
        if not self._entries or not text:
            return None
        
        result = self._entries.get(text)
        with self._lock:
            if result is not None:
                self._lookup_hits += 1
            else:
                self._lookup_misses += 1
        return result
    
    def get_exact_batch(self, texts: List[str]) -> Dict[str, str]:
        """
        Birden fazla metin için toplu exact match.
        
        Args:
            texts: Orijinal metinler listesi
            
        Returns:
            {original: translated} dict (sadece match olanlar)
        """
        if not self._entries:
            return {}
        
        matches = {}
        for text in texts:
            result = self._entries.get(text)
            if result:
                matches[text] = result
                self._lookup_hits += 1
            else:
                self._lookup_misses += 1
        return matches
    
    # ═══════════════════════════════════════════════════════════════════
    # YÖNETİM — TM kaynaklarını listele, sil, istatistik
    # ═══════════════════════════════════════════════════════════════════
    
    def list_available_sources(self) -> List[TMSource]:
        """
        tm/ klasöründeki mevcut TM kaynaklarını listeler.
        
        Returns:
            TMSource listesi
        """
        sources = []
        
        if not os.path.isdir(self.tm_dir):
            return sources
        
        for filename in sorted(os.listdir(self.tm_dir)):
            if not filename.endswith('.json'):
                continue
            
            filepath = os.path.join(self.tm_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                meta = data.get("meta", {})
                entries = data.get("entries", {})
                
                sources.append(TMSource(
                    name=meta.get("source_name", filename.replace('.json', '')),
                    language=meta.get("language", "unknown"),
                    entry_count=len(entries) if isinstance(entries, dict) else meta.get("entry_count", 0),
                    file_path=filepath,
                    created=meta.get("created", ""),
                    source_path=meta.get("source_path", ""),
                ))
            except Exception as e:
                logger.warning(f"TM metadata okunamadı: {filepath} — {e}")
        
        return sources
    
    def delete_source(self, file_path: str) -> bool:
        """
        Bir TM kaynağını siler.
        
        Args:
            file_path: Silinecek TM JSON dosya yolu
            
        Returns:
            Başarılı mı
        """
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"TM kaynağı silindi: {file_path}")
                
                # Bellekten de temizle
                if file_path in self._loaded_sources:
                    self._loaded_sources.remove(file_path)
                    # Entries'i yeniden yükle (silinen kaynak çıkmalı)
                    remaining = [s for s in self._loaded_sources]
                    self.load_sources(remaining)
                
                return True
        except Exception as e:
            logger.error(f"TM silme hatası: {file_path} — {e}")
        return False
    
    @property
    def entry_count(self) -> int:
        """Bellekteki toplam entry sayısı."""
        return len(self._entries)
    
    @property
    def loaded_source_count(self) -> int:
        """Yüklü kaynak sayısı."""
        return len(self._loaded_sources)
    
    @property
    def stats(self) -> Dict[str, int]:
        """Lookup istatistikleri."""
        total = self._lookup_hits + self._lookup_misses
        return {
            "entries": len(self._entries),
            "sources": len(self._loaded_sources),
            "hits": self._lookup_hits,
            "misses": self._lookup_misses,
            "hit_rate": round(self._lookup_hits / total * 100, 1) if total > 0 else 0.0,
        }
    
    @property
    def loaded_source_names(self) -> List[str]:
        """Yüklü kaynak isimlerini döndür."""
        names = []
        for path in self._loaded_sources:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                name = data.get("meta", {}).get("source_name", os.path.basename(path))
                entry_count = len(data.get("entries", {}))
                names.append(f"{name} ({entry_count})")
            except Exception:
                names.append(os.path.basename(path))
        return names
    
    def is_loaded(self) -> bool:
        """TM yüklü ve kullanılabilir mi?"""
        return len(self._entries) > 0
    
    def rename_source(self, file_path: str, new_name: str) -> Tuple[bool, str]:
        """
        Bir TM kaynağının adını değiştirir.
        
        Args:
            file_path: TM JSON dosya yolu
            new_name: Yeni kaynak adı
            
        Returns:
            (başarılı mı, mesaj)
        """
        try:
            if not os.path.isfile(file_path):
                return False, "File not found"
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            data["meta"]["source_name"] = new_name
            
            # Atomic write
            fd, tmp_path = tempfile.mkstemp(dir=self.tm_dir, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, file_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            logger.info(f"TM renamed: {new_name} ({file_path})")
            return True, f"Renamed to '{new_name}'"
        except Exception as e:
            logger.error(f"TM rename error: {file_path} — {e}")
            return False, str(e)
    
    def merge_sources(self, source_paths: List[str], new_name: str) -> Tuple[bool, str, str]:
        """
        Birden fazla TM kaynağını birleştirir ve yeni bir dosya oluşturur.
        
        Args:
            source_paths: Birleştirilecek TM dosya yolları
            new_name: Yeni kaynak adı
            
        Returns:
            (başarılı mı, mesaj, yeni dosya yolu)
        """
        try:
            merged_entries: Dict[str, str] = {}
            total_entries = 0
            
            for path in source_paths:
                if not os.path.isabs(path):
                    path = os.path.join(self.base_dir, path)
                
                if not os.path.isfile(path):
                    continue
                
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                entries = data.get("entries", {})
                for original, translated in entries.items():
                    if original and translated and original != translated:
                        if original not in merged_entries:
                            merged_entries[original] = translated
                            total_entries += 1
            
            if not merged_entries:
                return False, "No valid entries to merge", ""
            
            # Yeni dosya oluştur
            safe_name = re.sub(r'[^\w\-]', '_', new_name)
            filename = f"{safe_name}_merged.json"
            output_path = os.path.join(self.tm_dir, filename)
            
            # Dilleri birleştir
            languages = set()
            for path in source_paths:
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    lang = data.get("meta", {}).get("language", "unknown")
                    languages.add(lang)
                except Exception:
                    pass
            
            tm_data = {
                "meta": {
                    "source_name": new_name,
                    "language": ", ".join(sorted(languages)) if languages else "unknown",
                    "entry_count": len(merged_entries),
                    "created": datetime.now().isoformat(),
                    "merged_from": len(source_paths),
                    "version": "1.0"
                },
                "entries": merged_entries
            }
            
            # Atomic write
            fd, tmp_path = tempfile.mkstemp(dir=self.tm_dir, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(tm_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, output_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            logger.info(f"TM merged: {output_path} ({total_entries} entries from {len(source_paths)} sources)")
            return True, f"Merged {total_entries} entries from {len(source_paths)} sources", output_path
        except Exception as e:
            logger.error(f"TM merge error: {e}")
            return False, str(e), ""
    
    def export_source(self, file_path: str, export_path: str) -> Tuple[bool, str]:
        """
        Bir TM kaynağını belirtilen yere kopyalar (yedekleme).
        
        Args:
            file_path: Kaynak TM dosya yolu
            export_path: Hedef dosya yolu
            
        Returns:
            (başarılı mı, mesaj)
        """
        try:
            if not os.path.isfile(file_path):
                return False, "Source file not found"
            
            import shutil
            shutil.copy2(file_path, export_path)
            logger.info(f"TM exported: {file_path} -> {export_path}")
            return True, f"Exported to {export_path}"
        except Exception as e:
            logger.error(f"TM export error: {e}")
            return False, str(e)
