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
from typing import Dict, Tuple, Optional


COMMON_ENGLISH_STOPWORDS: frozenset = frozenset({
    # Articles
    "a", "an", "the",
    # Pronouns & Possessives
    "i", "me", "my", "myself", "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "whose", "this", "that", "these", "those",
    # Prepositions
    "about", "above", "across", "after", "against", "along", "among", "around",
    "at", "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "by", "down", "during", "except", "for", "from", "in", "inside", "into",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past",
    "through", "throughout", "to", "toward", "towards", "under", "underneath",
    "until", "unto", "up", "upon", "with", "within", "without",
    # Conjunctions
    "and", "but", "or", "nor", "so", "yet", "although", "because", "since",
    "unless", "while", "where", "whereas", "whether", "though", "if", "than",
    "then", "both", "either", "neither",
    # Auxiliary verbs, Be verbs, Modals
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did", "doing", "done",
    "can", "could", "shall", "should", "will", "would", "may", "might", "must",
    # Adverbs, Quantifiers & Common discourse markers
    "all", "any", "each", "few", "more", "most", "other", "some", "such",
    "no", "not", "only", "own", "same", "too", "very", "just", "now",
    "here", "there", "when", "why", "how", "again", "further", "once",
    "already", "always", "never", "ever",
    # Common generic speaker nouns / roles in Ren'Py scripts (should not be locked as untranslated glossary)
    "man", "men", "woman", "women", "boy", "boys", "girl", "girls", "guy", "guys",
    "kid", "kids", "child", "children", "person", "people", "someone", "anyone",
    "everyone", "nobody", "nothing", "something", "everything",
    "nurse", "doctor", "teacher", "student", "guard", "stranger", "crowd",
    "voice", "narrator", "friend", "mother", "father", "mom", "dad",
    "sister", "brother", "son", "daughter", "clerk", "waiter", "waitress",
    "officer", "cop", "soldier", "driver", "boss",
})


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
            src_clean = src.strip()
            if not src_clean:
                continue
            src_lower = src_clean.lower()
            dst_clean = (dst or "").strip()
            dst_lower = dst_clean.lower()

            # Skip common English stopwords when:
            # 1. Identity protection (e.g. "To" -> "To", "Her" -> "Her", "Man" -> "Man")
            # 2. Very short grammatical stopwords (len <= 3, e.g. "to", "in", "at", "an")
            if src_lower in COMMON_ENGLISH_STOPWORDS and (src_lower == dst_lower or len(src_clean) <= 3):
                continue

            # Case sensitivity:
            # - Short terms (len <= 3) must ALWAYS be case-sensitive (e.g. HP, MP, AI, UI)
            # - Capitalized terms (names/proper nouns like Will, May, Rose) must match case-sensitively
            #   so they never match lowercase verbs/nouns (will, may, rose)
            if len(src_clean) <= 3 or src_clean[0].isupper():
                pattern = re.compile(r"\b" + re.escape(src_clean) + r"\b")
            else:
                pattern = re.compile(r"(?i)\b" + re.escape(src_clean) + r"\b")

            if not pattern.search(result):
                continue

            # Detect spans already guarded by syntax guard (<ph id="...">...</ph> or ⟦...⟧)
            # Never inject glossary placeholders inside existing placeholders (avoids nested corruption)
            protected_spans = [
                (m.start(), m.end())
                for m in re.finditer(r'<ph\b[^>]*>.*?</ph>|\u27e6[^\u27e7]*\u27e7', result, re.DOTALL)
            ]

            def replace_func(
                match,
                _counter=[counter],  # noqa: B006 - shared on purpose: binds this iteration's counter
                _xml=xml_mode,
                _dst=dst,
                _ns=token_namespace,
                _spans=protected_spans,
            ):
                start, end = match.start(), match.end()
                for ps, pe in _spans:
                    if ps <= start and end <= pe:
                        return match.group(0)  # Inside an existing protected placeholder, skip!

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
            src_clean = src.strip()
            if not src_clean:
                continue
            src_lower = src_clean.lower()
            dst_clean = (dst or "").strip()
            dst_lower = dst_clean.lower()

            # Skip common English stopwords in target replacement to prevent corrupting Turkish words
            # (e.g. Turkish "her gün" corrupted by English "Her", Turkish "bir an" corrupted by "An")
            if src_lower in COMMON_ENGLISH_STOPWORDS and (src_lower == dst_lower or len(src_clean) <= 3):
                continue

            if len(src_clean) <= 3 or src_clean[0].isupper():
                pattern = re.compile(r"\b" + re.escape(src_clean) + r"\b")
            else:
                pattern = re.compile(r"(?i)\b" + re.escape(src_clean) + r"\b")

            if pattern.search(result):
                result = pattern.sub(
                    lambda m, _dst=dst: preserve_case(m.group(0), _dst), result
                )

        return result
