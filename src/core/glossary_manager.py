# -*- coding: utf-8 -*-
"""
Glossary Manager
================

Merkezi terim sözlüğü yöneticisi.
Metin çevrilmeden önce terimleri placeholder ile koruma (protect)
ve çeviri sonrası terimleri uygulama (apply_glossary) işlemlerini yönetir.
"""

import re
import uuid
from typing import Dict, Tuple, Optional, Any


def preserve_case(src: str, dst: str) -> str:
    """Kaynaktaki harf durumunu (upper/capitalize) hedefe uygula."""
    if not src or not dst:
        return dst
    if src.isupper():
        return dst.upper()
    if src[0].isupper():
        return dst.capitalize()
    return dst


class GlossaryManager:
    """Terim sözlüğü işleme ve koruma yöneticisi."""

    @staticmethod
    def sort_glossary_terms(glossary: Dict[str, str]) -> list:
        """Terimleri uzunluğa göre azalan sırayla döndür (uzun terimler önce eşleşir)."""
        return sorted(
            [item for item in glossary.items() if item[0] and item[1]],
            key=lambda x: -len(x[0]),
        )

    @classmethod
    def protect_terms(
        cls,
        text: str,
        glossary: Dict[str, str],
        xml_mode: bool = False,
    ) -> Tuple[str, Dict[str, str]]:
        """
        Çeviri öncesi terimleri placeholder'a dönüştürerek korur.
        
        Args:
            text: Orijinal metin
            glossary: {kaynak: hedef} sözlüğü
            xml_mode: AI/XML modunda <ph> etiketi mi yoksa hex token mi kullanılacak
            
        Returns:
            Tuple[Korumalı metin, Placeholder sözlüğü]
        """
        if not text or not glossary:
            return text, {}

        placeholders: Dict[str, str] = {}
        counter = 0
        token_namespace = uuid.uuid4().hex[:6].upper()
        sorted_terms = cls.sort_glossary_terms(glossary)

        result = text
        for src, dst in sorted_terms:
            pattern = re.compile(r"(?i)\b" + re.escape(src) + r"\b")

            def replace_func(
                match,
                _counter=[counter],
                _xml=xml_mode,
                _dst=dst,
                _ns=token_namespace,
            ):
                matched_text = match.group(0)
                idx = _counter[0]
                _counter[0] += 1
                if _xml:
                    key = f'<ph id="G{idx}">{matched_text}</ph>'
                    placeholders[f"G{idx}"] = _dst
                else:
                    key = f"\u27e6RLPH{_ns}_G{idx}\u27e7"
                    placeholders[key] = _dst
                return key

            result = pattern.sub(replace_func, result)
            counter = len(placeholders)

        return result, placeholders

    @classmethod
    def apply_glossary(
        cls,
        text: str,
        glossary: Dict[str, str],
        original_text: Optional[str] = None,
    ) -> str:
        """
        Çevrilmiş metin üzerinde terim sözlüğünü uygular.
        
        Args:
            text: Çevrilmiş metin
            glossary: {kaynak: hedef} sözlüğü
            original_text: Orijinal kaynak metin (tam eşleşme kontrolü için)
            
        Returns:
            Terimleri uygulanmış metin
        """
        if not glossary or not text:
            return text

        # 1. Tam eşleşme kontrolü
        if original_text:
            orig_stripped = original_text.strip()
            for src, dst in glossary.items():
                if src.lower() == orig_stripped.lower():
                    return dst

        # 2. Metin içinde arama ve değiştirme (uzun terimler önce)
        sorted_terms = cls.sort_glossary_terms(glossary)
        result = text
        for src, dst in sorted_terms:
            pattern = re.compile(r"(?i)\b" + re.escape(src) + r"\b")
            if pattern.search(result):
                result = pattern.sub(
                    lambda m, _dst=dst: preserve_case(m.group(0), _dst), result
                )

        return result
