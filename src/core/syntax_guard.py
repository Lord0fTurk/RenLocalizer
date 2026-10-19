# -*- coding: utf-8 -*-
# MIT License - RenLocalizer
"""
Syntax Guard Module (v3.3 Ren'Py 8 Full Compliance)
====================================================
Ren'Py ve Python sözdizimini (değişkenler, tagler, format karakterleri) koruma ve geri yükleme işlemlerini yönetir.
Bu modül, çeviri motorlarının (Google, DeepL) kod yapısını bozmasını engellemek için "Askeri Düzeyde" koruma sağlar.

Architecture & Optimizations (v2.6.4+):
---------------------------------------
1. **Hybrid Protection Strategy:**
   - **Wrapper Tags:** Dış katmandaki tagler ({i}...{/i}) tamamen kesilip alınır (Token tasarrufu + Güvenlik).
   - **Internal Tokens:** İçerideki değişkenler ([var], %s) HTML TOKEN formatlı placeholder'lara dönüştürülür.
   
2. **Regex Pooling:**
   - Tüm regex'ler modül seviyesinde derlenir (Pre-compiled).
   - Python'un `re` motoru için optimize edilmiş "Atomic Group" benzeri yapılar kullanılır.
   
3. **Bracket Healing (Cerrahi Onarım):**
   - Çeviri sonrası oluşan "Google Hallucination" hatalarını (örn: `[ [`) analiz eder ve onarır.
   - Nested (iç içe) değişken yapılarını (`[list [ 1 ]]`) tespit edip düzeltir.

4. **Python Formatting Support:**
   - `%s`, `%d`, `%f`, `%i` ve `%(var)s` gibi standart Python formatlarını otomatik tanır ve korur.
"""

import re
import uuid
import unicodedata
from typing import Dict, Tuple, List

# =============================================================================
# SCRIPT TRANSLITERATION RECOVERY (Google Translate Anti-Corruption)
# =============================================================================
# Google Translate bazı dillerde token isimlerini hedef dil alfabesine translitere ediyor.
# Örnek: Rusça'da VAR0 → ВАР0 (Kiril), Yunanca'da TAG0 → ΤΑΓ0 (Yunan)
# Bu map FONETİK eşleşmeye göre — görsel değil (В=V sesi, Р=R sesi)
# Recovery sadece token-benzeri bölgelerde (büyük harf + rakam) uygulanır.
_CYRILLIC_TO_LATIN = str.maketrans({
    'А': 'A', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E',
    'И': 'I', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N',
    'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T',
    'У': 'U', 'Х': 'X',
})

_GREEK_TO_LATIN = str.maketrans({
    'Α': 'A', 'Β': 'B', 'Γ': 'G', 'Δ': 'D', 'Ε': 'E',
    'Ι': 'I', 'Κ': 'K', 'Μ': 'M', 'Ν': 'N', 'Ο': 'O',
    'Ρ': 'R', 'Σ': 'S', 'Τ': 'T', 'Χ': 'X',
})

# Tüm non-Latin büyük harfleri tek regex ile yakala: token-benzeri sekanslar
# Pattern: En az 2 uppercase (Latin veya non-Latin) + rakam/underscore dizisi
# v2.7.2: Boşluk ile ayrılmış combo'ları da yakala (ВАР 0 → VAR0)
_TRANSLITERATED_TOKEN_RE = re.compile(
    r'[A-ZА-ЯΑ-Ω][A-ZА-ЯΑ-Ω0-9_]*'
    r'(?:'
    r'(?:\s*[0-9]+)+'     # Sequence of digits with optional spaces
    r'|(?:\s*_[0-9]+)+'   # Sequence of _digits with optional spaces
    r'|_[A-ZА-ЯΑ-Ω0-9_]+'   # Standard underscore identifiers
    r')'
)

# Ren'Py variable patterns
# Ren'Py variable patterns (Individual)
RENPY_VAR_PATTERN = re.compile(r'\[([^\[\]]+)\]')  # [variable]
RENPY_TAG_PATTERN = re.compile(r'\{([^\{\}]+)\}')  # {tag}

# =============================================================================
# SHARED REGEX PATTERNS (Single Source of Truth)
# =============================================================================
# Base building blocks for protection regexes
_PAT_PCT = r'%%'                             # Literal % (double percent)
# v2.6.6: CRITICAL FIX - Handle escaped brackets properly
# Strategy: Only match COMPLETE escaped pairs [[...]] or {{...}} to protect content atomically
# For incomplete cases like [[Phone], let normal [...]  matching handle the content
# This prevents incomplete [[  from breaking subsequent [variable] patterns
_PAT_ESC_COMPLETE = r'\[\[.*?\]\]|\{\{.*?\}\}'  # Complete pairs only: [[...]] or {{...}}
_PAT_ESC_INCOMPLETE = r'\}\}|\]\]'              # Only closing brackets as fallback (not opening)
# v2.8.17: `[[` on its own is Ren'Py's escape for a literal `[`, so the words
# after it are text — not a variable. "\\[Sleep until the next morning\\]"
# normalises to "[[Sleep until the next morning]", and without this the [...]
# pattern swallowed the whole sentence into one placeholder. Complete `[[..]]`
# pairs still match first, so their long-standing atomic handling is unchanged.
_PAT_ESC_LONE_OPEN = r'\[\[|\{\{'
_PAT_ESC = f"({_PAT_ESC_COMPLETE}|{_PAT_ESC_INCOMPLETE}|{_PAT_ESC_LONE_OPEN})"  # pairs, closers, then lone openers
# v2.8.17: Ren'Py also escapes with a backslash — "\[Sleep until the next morning\]"
# is literal display text, not interpolation. Without this the [...] pattern matched
# from the bracket after the backslash and swallowed the whole sentence into one
# placeholder, so the words never reached the translator (309 such menu choices in
# FunTanariZ 1.12 alone). Protecting just the escape keeps the text translatable and
# round-trips the escape untouched.
_PAT_BACKSLASH_ESC = r'\\[\[\]{}]'          # \[ \] \{ \} — escaped literal bracket/brace
_PAT_TAG = r'\{[^\}]+\}'                     # {tag} (greedy match inside braces)
_PAT_EMPTY_BRACE = r'\{\}'                   # Empty {} (Python .format() positional placeholder)
# _PAT_DISAMBIG: Disambiguation tags like {#comment}, {#game} - MUST be preserved exactly
_PAT_DISAMBIG = r'\{#[^}]+\}'
# _PAT_VAR: Matches [variable], [obj.attr], [list[index]], and [var!t] (translatable flag)
# OPTIMIZED v2.6.6: Prevents catastrophic backtracking on deeply nested brackets
# Uses non-backtracking approach: Match content inside [...] but avoid complex alternation
# Old pattern had catastrophic backtracking: r"\[(?:[^\[\]\n'\"]+|'[^']*'|\"[^\"]*\"|\[[^\[\]\n]*\])+\]"
# New: Simpler but safer - matches [...] with anything inside (more lenient, less prone to hang)
_PAT_VAR = r"\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]"
#: A Ren'Py interpolation holds a Python expression, so it never contains a bare
#: space. "[player_name]" and "[obj.attr]" are variables; "[Sleep until the next
#: morning]" is a label the player reads (an escaped literal bracket that has
#: been unescaped). Components that strip or compare placeholders must share
#: this definition, or they silently drop such labels.
INTERPOLATION_RE = re.compile(r'\[[^\[\]\s]+\]')


_PAT_FMT = r'%\([^)]+\)[sdfi]|%[sdfi]'       # Python formatting: %(var)s or %s (Support for s, d, f, i)
_PAT_QMK = r'\?[A-Za-z]\d{3}\?'              # ?A000? style
_PAT_UNI = r'\u27e6(?:[A-Z][A-Z0-9_]{1,24}|RLPH[A-F0-9]{6}_\d+)\u27e7'  # Legacy + internal unicode token style

# v2.8.3: Ren'Py lenticular bracket ruby/furigana text — 【base｜ruby】 or 【base|ruby】
# Must be protected atomically; splitting breaks the furigana structure.
# The vertical bar separates base text from ruby annotation.
_PAT_RUBY = r'【[^】]*[｜|][^】]*】'

# Combined pattern string (Order matters: most specific/longest first)
# v2.6.6: Complete escaped pairs MUST match before variables to prevent partial breakage
# Example: [[Phone]] matches as atomic esc pair; bare [[Phone] won't match as [[ so [Phone] matches normally
# v2.8.3: Ruby/furigana lenticular brackets added before variables to ensure correct atomic capture
_PROTECT_PATTERN_STR = f"({_PAT_BACKSLASH_ESC}|{_PAT_DISAMBIG}|{_PAT_ESC}|{_PAT_RUBY}|{_PAT_TAG}|{_PAT_EMPTY_BRACE}|{_PAT_FMT}|{_PAT_PCT}|{_PAT_QMK}|{_PAT_UNI}|{_PAT_VAR})"

# Pre-compiled Regexes (Module Level Optimization)
PROTECT_RE = re.compile(_PROTECT_PATTERN_STR)

# Specific Regexes for protect_renpy_syntax logic (Tag extraction)
# These capture the wrapper tags to identify them
# Ren'Py 8 tag list: https://www.renpy.org/doc/html/text.html#text-tags
_OPEN_TAG_RE = re.compile(
    r'^(\{(?:'
    # Style tags
    r'i|b|u|s|plain|'
    # Control tags (nw can have argument: {nw=2})
    r'fast|nw(?:=[\d.]+)?|done|'
    # Timing tags
    r'w(?:=[\d.]+)?|p(?:=[\d.]+)?|cps(?:=\*?[\d.]+)?|'
    # Visual style tags
    r'color(?:=[^}]+)?|size(?:=[^}]+)?|font(?:=[^}]+)?|outlinecolor(?:=[^}]+)?|'
    r'alpha(?:=[^}]+)?|k(?:=[^}]+)?|'
    # Ruby text (furigana) tags
    r'rb|rt|'
    # Alternate ruby top (Ren'Py 8)
    r'art|'
    # Spacing tags
    r'space(?:=[^}]+)?|vspace(?:=[^}]+)?|'
    # Image/Link tags
    r'image(?:=[^}]+)?|a(?:=[^}]+)?|'
    # Accessibility tags (Ren'Py 8)
    r'alt(?:=[^}]+)?|noalt|'
    # Shader/Transform tags (Ren'Py 8)
    r'shader(?:=[^}]+)?|transform(?:=[^}]+)?|'
    # Variable font tags (Ren'Py 8): {instance=heavy}, {axis:width=125}
    r'instance(?:=[^}]+)?|axis:[a-z]+(?:=[^}]+)?|'
    # OpenType feature tag (Ren'Py 8): {feature:liga=0}
    r'feature:[a-z]+(?:=[^}]+)?|'
    # Vertical/Horizontal text tags (Ren'Py 8)
    r'horiz|vert|'
    # Clear tag (Ren'Py 8)
    r'clear'
    r')\})+'
)

_CLOSE_TAG_RE = re.compile(
    r'(\{/(?:'
    # Core style tags
    r'i|b|u|s|plain|'
    # Visual style tags
    r'color|size|font|outlinecolor|alpha|cps|k|'
    # Link tag
    r'a|'
    # Ruby text tags
    r'rb|rt|art|'
    # Accessibility tags
    r'alt|noalt|'
    # Shader/Transform tags
    r'shader|transform|'
    # Variable font tags (Ren'Py 8)
    r'instance|axis|'
    # OpenType feature tag (Ren'Py 8)
    r'feature|'
    # Vertical/Horizontal text tags (Ren'Py 8)
    r'horiz|vert'
    # v2.8.4: Allow optional trailing sentence-final punctuation after close tags.
    # Patterns like {i}text{/i}. would previously fail to match because $
    # did not anchor past the trailing period.  We now capture it so the
    # close tag can still form a wrapper-pair and the punctuation is
    # moved inside the inner text (visually equivalent in Ren'Py).
    r')\})+([.!?…\u2026]*)$'
)

# Aggressive spaced pattern for restoration (handles AI adding spaces)
# Aggressive spaced pattern for restoration (handles AI adding spaces)
# Pattern: X R P Y X [CORE with spaces] X R P Y X
# OPTIMIZATION: Use \s* between major tokens (for Google's multi-spaces) but \s? inside chars
SPACED_RE_TEMPLATE = r'X\s?R\s?P\s?Y\s?X\s*{core_spaced}\s*X\s?R\s?P\s?Y\s?X'

def _make_spaced_core_pattern(core: str) -> str:
    """Convert 'VAR0' to 'V\\s?A\\s?R\\s?0' for flexible matching."""
    # OPTIMIZATION: Use \s? instead of \s* for performance
    return r'\s?'.join(re.escape(c) for c in core)


# Unicode PUA Markers - These characters are in the Private Use Area
# and will generally be ignored/preserved by translation engines like Google Translate
# DEPRECATED BUT KEPT FOR FALLBACK
PUA_START = '\uE000'  # Marker for start/end of a placeholder (VAR, TAG, etc)
ESC_OPEN  = '\uE001'  # Marker for [[
ESC_CLOSE = '\uE002'  # Marker for ]]

def protect_renpy_syntax(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Ren'Py sözdizimini HTML TOKEN + WRAPPER yöntemiyle korur (v2.6.7+).
    
    STRATEJİ:
    1. WRAPPER TAGLER → Çıkarılır ve pair'ler (açılış, kapalış) atomik olarak saklanır.
    2. TOKENİZASYON → [var], {tag}, [[ vb. yapılar "VAR0", "ESC_OPEN" gibi tokenlara dönüştürülür.
    3. INNER CLOSING TAGS → Wrapper'ın dışında kapalış tag'ler normal token olarak çalışır,
       ama wrapper içi kapalış tag'ler skip edilir (confusion'ı önlemek için).
    
    v2.6.7+ FIX: Wrapper pair tracking - closing tag'ler ayrı token olarak sayılmaz.
    """
    placeholders: Dict[str, str] = {}
    result_text = text
    token_namespace = uuid.uuid4().hex[:6].upper()
    
    # AŞAMA 1: Wrapper tag pair'lerini tespit et ve çıkar (START AND END ONLY)
    # v3.2 FIX: Orphaned tag loss prevention — tags that can't form valid pairs
    # are reinserted into the text so PROTECT_RE can tokenize them normally.
    wrapper_pairs = []  # List of (open_tag, close_tag) tuples
    
    # Extract opening wrapper tags from START of string
    opening_tags = []
    _removed_opening_str = ""
    opening_match = _OPEN_TAG_RE.match(result_text)
    if opening_match:
        _removed_opening_str = opening_match.group(0)
        result_text = result_text[len(_removed_opening_str):]  # Remove opening tags from start
        for tag_match in re.finditer(r'\{[^}]+\}', _removed_opening_str):
            opening_tags.append(tag_match.group(0))
    
    # Extract closing wrapper tags from END of string
    closing_tags = []
    _removed_closing_str = ""
    closing_match = _CLOSE_TAG_RE.search(result_text)
    if closing_match:
        _removed_closing_str = closing_match.group(0)
        # v2.8.4: If trailing punctuation was captured (group 2), keep it in the
        # inner text so the close tag can still form a valid wrapper-pair.
        # e.g. "{i}text{/i}." → inner="text.", wrapper=({i},{/i})
        # The period ends up inside the italic, which is visually identical.
        _trailing_punct = closing_match.group(2) or ''
        result_text = result_text[:closing_match.start()] + _trailing_punct
        for tag_match in re.finditer(r'\{/[^}]+\}', _removed_closing_str):
            closing_tags.append(tag_match.group(0))
        closing_tags.reverse()  # Match them in correct nesting order
    
    # v3.2 FIX: Validate wrapper pairs by tag TYPE and reinsert unmatched tags.
    # Previous code paired by INDEX which could lose orphaned tags entirely.
    _remaining_closes = list(closing_tags)
    _matched_pairs = []
    _unmatched_opens = []
    
    for open_tag in opening_tags:
        # Extract tag name: {color=#fff} -> color, {b} -> b
        # Also handle colon syntax: {feature:liga=0} -> feature, {axis:width=125} -> axis
        _tag_inner = open_tag[1:-1]  # Remove { }
        _tag_name = _tag_inner.split('=')[0].split(':')[0].split()[0].lower().strip()
        _expected_close = '{/' + _tag_name + '}'
        
        # Find matching close in remaining
        _found_idx = None
        for j, close_tag in enumerate(_remaining_closes):
            if close_tag.lower().strip() == _expected_close:
                _found_idx = j
                break
        
        if _found_idx is not None:
            _matched_pairs.append((open_tag, _remaining_closes.pop(_found_idx)))
        else:
            _unmatched_opens.append(open_tag)
    
    # Reinsert unmatched tags back into the text so PROTECT_RE can tokenize them
    if _unmatched_opens:
        result_text = ''.join(_unmatched_opens) + result_text
    if _remaining_closes:
        # Remaining closes had no matching open — reinsert at end
        result_text = result_text + ''.join(reversed(_remaining_closes))
    
    # Store matched pairs as placeholders
    for i, (open_tag, close_tag) in enumerate(_matched_pairs):
        wrapper_pairs.append((open_tag, close_tag))
        placeholders[f"__WRAPPER_PAIR_{i}__"] = (open_tag, close_tag)
    
    # Handle whitespace ONLY between wrapper tags and content
    # v3.2 FIX: Only strip boundary spaces, not content-internal whitespace/newlines
    if wrapper_pairs and result_text:
        if result_text[0] == ' ':
            result_text = result_text.lstrip(' ')
        if result_text and result_text[-1] == ' ':
            result_text = result_text.rstrip(' ')
    
    # AŞAMA 2: Syntax Koruması (TOKEN mode, HTML NOT)
    counter = 0
    out_parts: List[str] = []
    last = 0
    
    # Inner closing tag pattern for skipping (v2.6.7+ fix)
    # These are closing tags that are part of wrapper pairs
    inner_closing_tags = {tag for _, tag in wrapper_pairs}
    
    for m in PROTECT_RE.finditer(result_text):
        start, end = m.start(), m.end()
        out_parts.append(result_text[last:start])
        
        token = m.group(0)
        
        # SKIP inner closing tags from wrapper pairs (v2.6.7+ fix)
        # This prevents them from becoming separate TAG tokens
        if token in inner_closing_tags:
            out_parts.append(token)  # Keep as-is, don't tokenize
            last = end
            continue
        
        # Token İsimlendirme (v2.7.2): Alfabe-Bağımsız Format ⟦N⟧
        # Eski format (VAR0, TAG1, ESC_PAIR2...) Latin harf içerdiği için
        # Google Translate bazı hedef dillerde translitere ediyordu:
        #   Rusça:  VAR0 → ВАР0, TAG0 → ТАГ0, ESC0 → ЕСК0
        #   C harfi özellikle sorunlu: Kiril'de C=С(=S) veya К(=K), geri dönüşüm imkansız
        # Unicode matematiksel köşeli parantezler ⟦⟧ (U+27E6/U+27E7) hiçbir dilde
        # translitere edilemez — Google bunlara "tanımsız sembol" olarak dokunmaz.
        key_content = f"\u27e6RLPH{token_namespace}_{counter}\u27e7"
        counter += 1
            
        # Placeholders map'e kaydet (Token -> Orijinal)
        placeholders[key_content] = token
        
        # Metne SADECE token'ı ekle (HTML yok)
        out_parts.append(key_content)
            
        last = end
        
    out_parts.append(result_text[last:])
    protected = ''.join(out_parts)
    
    # Fazla boşlukları temizle (ardışık boşluklar → tek boşluk)
    # v3.2 FIX: Newline'ları koru — sadece yatay boşlukları (space/tab) normalize et.
    # Eski kod: ' '.join(protected.split()) — bu \n karakterlerini yok ediyordu.
    protected = re.sub(r'[^\S\n]+', ' ', protected).strip()
    
    return protected, placeholders


def restore_renpy_syntax(text: str, placeholders: Dict[str, str]) -> str:
    """
    Tokenları (VAR0, TAG1...) ve eski formatları geri yükler.
    
    STRATEJİ:
    1. Tokenları Geri Yükle (VAR0 -> [var])
    2. HTML Span temizliği (Eğer yanlışlıkla HTML gönderildiyse)
    3. Eski sistemler (PUA, XRPYX) için fallback desteği
    4. Wrapper tagleri geri ekle (v2.6.7+ pair-based system)
    """
    if not text or not placeholders:
        return text
    
    # Wrapper tag'leri ve normal placeholder'ları ayır
    # v2.6.7+ FIX: Support both new wrapper pair system and old separate lists
    wrapper_pairs = []
    
    # Try new wrapper pair system first (v2.6.7+)
    for key, value in placeholders.items():
        if key.startswith("__WRAPPER_PAIR_"):
            if isinstance(value, tuple) and len(value) == 2:
                wrapper_pairs.append(value)
    
    # Fallback to old system for backwards compatibility
    if not wrapper_pairs:
        wrapper_open = placeholders.get("__WRAPPER_OPEN__", [])
        wrapper_close = placeholders.get("__WRAPPER_CLOSE__", [])
        if wrapper_open and wrapper_close:
            # Pair them up: first open with first close, etc.
            for i, open_tag in enumerate(wrapper_open):
                if i < len(wrapper_close):
                    wrapper_pairs.append((open_tag, wrapper_close[i]))
    
    # Normal placeholder'ları filtrele
    vars_only = {k: v for k, v in placeholders.items() 
                 if not k.startswith("__WRAPPER_") and not k.startswith("__TAG_")}
    
    # Eski __TAG_ sistemi için destek
    old_tags = {k: v for k, v in placeholders.items() if k.startswith("__TAG_")}
        
    result = text
    
    # AŞAMA 0: Unicode Bracket Token Restore (legacy + v3.3.1 namespaced format)
    # Google ⟦⟧ içine boşluk ekleyebilir: ⟦RLPHABC123_0⟧ → ⟦ RLPHABC123_0 ⟧.
    if vars_only and '\u27e6' in result:
        _unicode_token_re = re.compile(r'\u27e6\s*([^\u27e7]+?)\s*\u27e7')
        def _restore_unicode_token(match):
            token_inner = ''.join(match.group(1).split())
            token_inner = unicodedata.normalize('NFKC', token_inner).upper()
            if not re.fullmatch(r'[A-Z0-9_]+', token_inner):
                return match.group(0)
            token_key = f'\u27e6{token_inner}\u27e7'
            
            if token_key in vars_only:
                return vars_only[token_key]
                
            # Fuzzy match for Google altering the RLPH string + missing/extra hex characters
            if '_' in token_inner:
                suffix = '_' + token_inner.split('_')[-1] + '\u27e7'
                matches = [k for k in vars_only.keys() if k.endswith(suffix)]
                if len(matches) == 1:
                    return vars_only[matches[0]]
                    
            return match.group(0)
        result = _unicode_token_re.sub(_restore_unicode_token, result)
    
    # AŞAMA 0.1: Bracket-stripped / variant-bracket RLPH token recovery
    # Google bazen ⟦⟧ Unicode parantezlerini tamamen siler veya
    # [RLPH...], (RLPH...) gibi başka parantezlere dönüştürür.
    # Stage 0 sağlam ⟦⟧ tokenlarını yakalar; bu aşama kalanları toplar.
    if vars_only:
        # Inner → key haritası: "RLPHABC123_0" → "⟦RLPHABC123_0⟧"
        _rlph_inner_map = {}
        for _k in vars_only:
            if _k.startswith('\u27e6') and _k.endswith('\u27e7'):
                _rlph_inner_map[_k[1:-1]] = _k
        if _rlph_inner_map:
            # Opsiyonel herhangi bir parantez + RLPH içerik + opsiyonel kapanış
            _rlph_recovery_re = re.compile(
                r'[\u27e6\[\(\{【「〔〚]?\s*'
                r'([A-Z]{3,5}[A-Z0-9]{4,8}'
                r'(?:'
                r'(?:\s*[0-9]+)+'
                r'|(?:\s*_[0-9]+)+'
                r'|_[A-ZА-ЯΑ-Ω0-9_]+'
                r')'
                r')'
                r'\s*[\u27e7\]\)\}】」〕〛]?'
            )
            def _recover_bare_rlph(m):
                # Clean the inner content: strip all spaces and underscores for matching
                inner_raw = m.group(1)
                inner_clean = re.sub(r'[\s_]+', '', inner_raw).upper()
                inner_clean = unicodedata.normalize('NFKC', inner_clean)
                
                # Check against our map (also cleaned)
                for _inner_key, _full_key in _rlph_inner_map.items():
                    if inner_clean == re.sub(r'[\s_]+', '', _inner_key).upper():
                        return vars_only[_full_key]
                    
                # Fuzzy match by suffix remains (as second fallback)
                if '_' in inner_raw or ' ' in inner_raw:
                    # Last part after space or underscore
                    suffix = '_' + re.split(r'[\s_]+', inner_raw)[-1] + '\u27e7'
                    matches = [k for k in vars_only.keys() if k.endswith(suffix)]
                    if len(matches) == 1:
                        return vars_only[matches[0]]
                        
                return m.group(0)
            result = _rlph_recovery_re.sub(_recover_bare_rlph, result)
    
    # =========================================================================
    # BACKWARD COMPAT: Eski VAR0/TAG1/ESC_PAIR2 formatı için recovery aşamaları
    # Cache'lenmiş çeviriler veya eski sürüm placeholder'ları kullanabilir.
    # =========================================================================
    
    # AŞAMA 0.5: Script Transliteration Recovery (Kiril/Yunan → Latin)
    # Eski format token'ları (VAR0, TAG0...) Google Translate tarafından
    # translitere edilmiş olabilir: ВАР0 → VAR0
    if vars_only:
        def _recover_transliterated(match):
            original = match.group(0)
            normalized = original.translate(_CYRILLIC_TO_LATIN).translate(_GREEK_TO_LATIN)
            if normalized in vars_only:
                return normalized
            normalized_clean = re.sub(r'[\s_]+', '', normalized)
            
            # Check for cleaned version in vars_only
            for k in vars_only:
                if normalized_clean == re.sub(r'[\s_]+', '', k).upper():
                    return k
            return original
        
        result = _TRANSLITERATED_TOKEN_RE.sub(_recover_transliterated, result)
    
    # AŞAMA 0.6: Spaced Token Cleanup (eski format backward compat)
    # Google Translate "VAR 0" → "VAR0" türü space eklemiş olabilir
    if vars_only:
        spaced_pattern = re.compile(
            r'(VAR|TAG|ESC_PAIR|ESC_OPEN|ESC_CLOSE|ESC|DIS|PCT|XRPYX[A-Z]*)\s+(\d+|[A-Z_]*)'
        )
        
        def fix_spaced(match):
            prefix = match.group(1)
            suffix = match.group(2)
            original_token = prefix + suffix
            if original_token in vars_only:
                return original_token
            return match.group(0)
        
        result = spaced_pattern.sub(fix_spaced, result)

    # AŞAMA 1: Token Geri Yükleme (eski format VAR0, ESC_OPEN vb. + yeni ⟦N⟧)
    # Tüm keyleri tek bir regex ile aramak en hızlısıdır
    if vars_only:
        sorted_keys = sorted(vars_only.keys(), key=len, reverse=True)
        pattern_str = '(' + '|'.join(re.escape(k) for k in sorted_keys) + ')'
        token_pattern = re.compile(pattern_str)
        
        def token_replacer(match):
            return vars_only.get(match.group(1), match.group(0))
            
        result = token_pattern.sub(token_replacer, result)

    # AŞAMA 2: HTML Span İçindeki Tokenları Geri Yükle (Fallback)
    # Eğer bir şekilde HTML span içinde token geldiyse (<span...>VAR0</span>)
    # Yukarıdaki adım token'ı değiştirmiş olabilir ama span kalmış olabilir.
    # Yani <span...> [player] </span> olmuş olabilir.
    # Cleaner: Remove spanning tags if they wrap restored content?
    # Better: Just clean spans if explicit tokens were wrapped.
    
    # PUA Fallbacks and cleanups...
    if PUA_START in result:
        pua_pattern = re.compile(rf"{PUA_START}\s*(.*?)\s*{PUA_START}")
        result = pua_pattern.sub(lambda m: vars_only.get(m.group(1).strip(), m.group(0)), result)

    if ESC_OPEN in result.replace("[[", ""): # Check if raw ESC_OPEN string remains
        result = result.replace(ESC_OPEN, placeholders.get(ESC_OPEN, '[['))
    if ESC_CLOSE in result.replace("]]", ""):
        result = result.replace(ESC_CLOSE, placeholders.get(ESC_CLOSE, ']]'))
        
    # XRPYX Fallback
    if "XRPYX" in result:
             for k, v in vars_only.items():
                 if "XRPYX" in k and k in result:
                     result = result.replace(k, v)

    # AŞAMA 4: Wrapper tag pair'lerini geri yerleştir (v2.6.7+ fix)
    # Now using atomic wrapper pairs to prevent confusion
    if wrapper_pairs:
        for open_tag, close_tag in reversed(wrapper_pairs):
            # Check if the result is already wrapped by open_tag and close_tag to prevent double-wrapping
            res_stripped = result.strip()
            if res_stripped.startswith(open_tag) and res_stripped.endswith(close_tag):
                continue
            result = open_tag + result + close_tag
    
    # Eski __TAG_ sistemi uyumluluğu
    if old_tags:
        sorted_tags = sorted(old_tags.items(), key=lambda x: x[1][1] if isinstance(x[1], tuple) else 0)
        opening_tags = []
        closing_tags = []
        for tag_key, tag_data in sorted_tags:
            tag_value = tag_data[0] if isinstance(tag_data, tuple) else tag_data
            if tag_value.startswith('{/'):
                closing_tags.append(tag_value)
            elif tag_value.startswith('{') and not tag_value.startswith('{{'):
                opening_tags.append(tag_value)
        for tag in reversed(opening_tags):
            result = tag + result
        for tag in closing_tags:
            result = result + tag
    
    # AŞAMA 5: Final Temizlik (Google Hallucinations)
    result = re.sub(r'\[\s*\[', '[[', result)
    result = re.sub(r'\]\s*\]', ']]', result)
    result = re.sub(r'\[\s+([a-zA-Z0-9_]+)\s+\]', r'[\1]', result)
    result = re.sub(r'\[\s*(\d+)\s*\]', r'[\1]', result)

    # AŞAMA 5.25: Placeholder boundary spacing repair
    # Bazı motorlar placeholder'ı komşu kelimeye yapıştırabilir:
    #   Merhaba[player] -> Merhaba [player]
    #   [player]geldi   -> [player] geldi
    # Yalnızca [] değişken placeholder'larında ve yalnızca alfanümerik komşulukta
    # boşluk ekleriz; noktalama eklerinin (örn. [name]'s, Hello,[name]!) davranışı
    # korunur.
    bracket_placeholders = [
        value for value in vars_only.values()
        if isinstance(value, str) and value.startswith('[') and value.endswith(']')
    ]
    for placeholder in sorted(set(bracket_placeholders), key=len, reverse=True):
        result = re.sub(rf'(?<=\w){re.escape(placeholder)}', f' {placeholder}', result, flags=re.UNICODE)
        result = re.sub(rf'{re.escape(placeholder)}(?=\w)', f'{placeholder} ', result, flags=re.UNICODE)

    # AŞAMA 5.5: Fuzzy Recovery - Bracket içindeki bozuk boşlukları temizle
    # Google Translate bazen [player.name] → [player. name] veya [player .name] yapıyor
    # Hedef dile göre bu oran artıyor (SOV diller, Arapça, vb.)
    # Pattern: [içerik] içindeki gereksiz boşlukları kaldır ama yapıyı koru
    def fix_bracket_spaces(match):
        content = match.group(1)
        # Nokta etrafındaki boşlukları temizle: "player . name" → "player.name"
        content = re.sub(r'\s*\.\s*', '.', content)
        # Çoklu boşlukları tek boşluğa indir
        content = re.sub(r'\s+', ' ', content)
        # Baş ve sondaki boşlukları temizle
        content = content.strip()
        return f'[{content}]'
    
    # Bracket expresionları düzelt (değişken interpolation)
    result = re.sub(r'\[([^\[\]]+)\]', fix_bracket_spaces, result)
    
    # Tag Nesting Repair
    result = _repair_broken_tag_nesting(result)

    # Decode HTML entities
    result = result.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")

    return result


def _repair_broken_tag_nesting(text: str) -> str:
    """
    Ren'Py taglerinin ({i}, {b}, {color}...) iç içe geçme sırasını onarır.
    v2.6.6 OPTIMIZATION: Added safety checks to prevent hangs on pathological input.
    """
    try:
        if not text or '{' not in text:
            return text
        if '/' not in text: 
            return text
        
        # Safety: Skip if text is too long (prevent pathological cases)
        # Most realistic game text is < 1000 chars; if longer, skip repair
        if len(text) > 5000:
            return text

        # Regex: Matches {{...}} OR {...} using character classes to avoid JSON escape issues
        tag_re = re.compile(r'([{][{].*?[}][}]|[{][^{}]+[}])')
        
        tokens = tag_re.split(text)
        
        # Safety: If too many tokens, skip (might be pathological)
        if len(tokens) > 200:
            return text
        
        stack = []
        broken_indices = set()
        
        nesting_tags = {
            'b', 'i', 'u', 's', 'plain', 'font', 'color', 'size', 'alpha', 'k',
            'rt', 'rb', 'art', 'a', 'cps', 'shader', 'transform',
            # Ren'Py 8 additions
            'alt', 'noalt', 'outlinecolor', 'instance', 'axis', 'feature',
            'horiz', 'vert',
        }
        
        for i, token in enumerate(tokens):
            # Skip empty tokens or non-tags
            if not token or not token.startswith('{'):
                continue
                
            if token.startswith('{{'):
                continue
                
            try:
                # Remove { and } and strip whitespaces
                content = token[1:-1].strip()
                if not content: continue
                
                is_closing = content.startswith('/')
                
                if is_closing:
                    # Remove / and get tag name
                    tag_name_part = content[1:].strip()
                    tag_name = tag_name_part.split()[0] if tag_name_part else ""
                else:
                     # Get tag name before = or : or space
                     # Handles: {feature:liga=0} -> feature, {axis:width=125} -> axis
                    tag_name = content.split('=')[0].split(':')[0].split()[0]
                
                tag_name = tag_name.lower().strip()
                
                if tag_name not in nesting_tags:
                    continue
                    
                if not is_closing:
                    stack.append((i, tag_name))
                else:
                    if not stack:
                        # ORPHAN CLOSING TAG -> DELETE IT
                        broken_indices.add(i)
                    else:
                        last_idx, last_name = stack[-1]
                        if last_name == tag_name:
                            stack.pop()
                        else:
                            # Mismatched nesting (e.g. {size}{color}{/size})
                            # Find matching opened tag further down
                            found_idx = -1
                            for j in range(len(stack)-1, -1, -1):
                                if stack[j][1] == tag_name:
                                    found_idx = j
                                    break
                            
                            if found_idx != -1:
                                stack = stack[:found_idx] # pop everything above it
                            else:
                                broken_indices.add(i) # Tag never opened, so delete closing
            except Exception:
                continue
                
        if not broken_indices:
            return text
            
        new_tokens = []
        for i, token in enumerate(tokens):
            if i not in broken_indices:
                new_tokens.append(token)
            
        return "".join(new_tokens)
        
    except Exception:
        # Failsafe: Return original text if anything goes wrong
        return text



def validate_translation_integrity(text: str, placeholders: Dict[str, str],
                                    skip_glossary: bool = True) -> List[str]:
    """
    Çevirinin bütünlüğünü doğrular (tüm orijinal tag'ler yerinde mi?).
    Eksik orijinal tag'lerin listesini döner.
    
    NOT: Bu fonksiyon artık sadece UYARI amaçlıdır, çeviriyi reddetmez.
    Boş liste dönerse tüm placeholder'lar başarıyla geri yüklenmiş demektir.
    
    Optimizasyon: clean_text sadece gerektiğinde hesaplanır (lazy evaluation).
    
    Args:
        text (str): Kontrol edilecek çevrilmiş metin
        placeholders (Dict[str, str]): placeholder -> orijinal değer sözlüğü
        skip_glossary (bool): True ise sözlük (glossary) yer tutucuları atlanır.
            Glossary tokenları (_G prefix) sözdizimi değildir — eksik olmaları
            çeviriyi bozmaz, sadece tercih edilen sözcüğün uygulanmadığı anlamına gelir.
        
    Returns:
        List[str]: Eksik orijinal değerlerin listesi (boşsa başarılı)
    """
    if not placeholders:
        return []
        
    missing = []
    clean_text = None  # Lazy: sadece gerekirse hesapla
    
    # Glossary key pattern: ⟦RLPH{ns}_G{n}⟧
    _GLOSSARY_KEY_RE = re.compile(r'_G\d+\u27e7$')
    
    for key, original in placeholders.items():
        # Wrapper ve eski tag sistemlerini atla
        if key.startswith("__WRAPPER_") or key.startswith("__TAG_"):
            continue
            
        # Liste ise (wrapper tag listesi), atla
        if isinstance(original, list):
            continue
            
        # Tuple ise (eski tag pozisyon bilgisi), atla
        if isinstance(original, tuple):
            continue
        
        # Glossary placeholder'ları atla (sözdizimi değildir)
        # Key format: ⟦RLPH{ns}_G{n}⟧  —  _G prefix glossary olduğunu gösterir
        if skip_glossary and _GLOSSARY_KEY_RE.search(key):
            continue
            
        # Hızlı yol: direkt kontrol
        if original in text:
            continue
            
        # Yavaş yol: toleranslı kontrol (boşluksuz ve case-insensitive)
        if clean_text is None:
            clean_text = text.replace(" ", "").lower()
            
        clean_original = original.replace(" ", "").lower()
        if clean_original not in clean_text:
            missing.append(original)
                  
    # Strict bracket check (unbalanced brackets at end)
    stripped = text.strip()
    if stripped.endswith('[') or stripped.endswith('{'):
        missing.append("UNBALANCED_BRACKET_END")
        
    # Tag Nesting Check (Post-repair validation)
    # Eğer repair fonksiyonu çalışmasına rağmen hala sorun varsa
    if clean_text: # Lazy computed check re-use
        pass # Şimdilik sadece structural check yeterli, derin nesting analizi pahalı olabilir.

    return missing


def inject_missing_placeholders(translated_text: str, protected_text: str,
                                 placeholders: Dict[str, str],
                                 missing_originals: List[str]) -> str:
    """
    Google Translate'in tamamen sildiği RLPH tokenlarının orijinal değerlerini
    çevrilen metne oransal pozisyonda enjekte eder.
    
    Google bazen ⟦RLPH...⟧ tokenlarını tamamen siler (bracket dönüşümü değil,
    tam silme). Bu durumda ne Stage 0 ne Stage 0.1 kurtarabilir.
    Bu fonksiyon son çare olarak çevrilmiş metne eksik değişkenleri
    orijinal metindeki konumlarına oranla yerleştirir.
    
    Strateji:
        1. Her eksik original_value → hangi RLPH key'e ait bul
        2. O key'in protected_text içindeki pozisyonunu bul (%oran)
        3. Aynı oranı translated_text'e uygula ve orijinal değeri yerleştir
    
    Args:
        translated_text: restore sonrası çevrilen metin (eksik değişkenlerle)
        protected_text: Google'a gönderilen korunmuş metin (RLPH tokenlerle)
        placeholders: tam placeholder sözlüğü
        missing_originals: validate_translation_integrity'nin döndürdüğü eksik liste
        
    Returns:
        str: Eksik değişkenler enjekte edilmiş çevrilen metin
    """
    if not missing_originals or not translated_text or not protected_text:
        return translated_text
    
    # Build reverse map: original_value → RLPH key
    value_to_key = {}
    for key, val in placeholders.items():
        if isinstance(val, str):
            value_to_key[val] = key
    
    # Collect (position_ratio, original_value) pairs
    insertions = []
    protected_len = len(protected_text)
    
    for orig_val in missing_originals:
        if orig_val == "UNBALANCED_BRACKET_END":
            continue
        rlph_key = value_to_key.get(orig_val)
        if not rlph_key:
            continue
        
        # Find token position in protected text
        pos = protected_text.find(rlph_key)
        if pos < 0:
            continue
        
        # Calculate proportional position
        ratio = pos / protected_len if protected_len > 0 else 0.5
        insertions.append((ratio, orig_val))
    
    if not insertions:
        return translated_text
    
    # Sort by position (left to right)
    insertions.sort(key=lambda x: x[0])
    
    # Insert from right to left to preserve positions
    result = translated_text
    trans_len = len(result)
    
    for ratio, orig_val in reversed(insertions):
        insert_pos = int(ratio * trans_len)
        
        # Find a safe insertion point — prefer ACTUAL word boundaries (spaces)
        # Only real spaces count; text start/end are fallback only.
        # ±20 chars arama: en yakın boşluk pozisyonunu bul
        best_pos = None
        for delta in range(0, 21):
            for candidate in [insert_pos + delta, insert_pos - delta]:
                if 0 <= candidate <= len(result):
                    # Actual space boundary check — NOT start/end of text
                    if (candidate > 0 and result[candidate - 1] == ' ') or \
                       (candidate < len(result) and result[candidate] == ' '):
                        best_pos = candidate
                        break
            else:
                continue
            break
        
        # Fallback: no space found within ±20 chars → snap to nearest text edge
        # to avoid splitting words in the middle
        if best_pos is None:
            dist_start = insert_pos
            dist_end = len(result) - insert_pos
            best_pos = 0 if dist_start <= dist_end else len(result)
        
        # Insert with surrounding spaces — always ensure space around injected value
        left = result[:best_pos].rstrip()
        right = result[best_pos:].lstrip()
        if left and right:
            result = f"{left} {orig_val} {right}"
        elif right:
            result = f"{orig_val} {right}"
        elif left:
            result = f"{left} {orig_val}"
        else:
            result = orig_val
    
    # Normalize double spaces
    result = re.sub(r'  +', ' ', result).strip()
    
    return result


# =============================================================================
# DELIMITER-AWARE TRANSLATION (v2.7.2)
# =============================================================================
# Bazı oyun geliştiricileri tek bir string içinde | (pipe) veya benzeri
# ayırıcılar kullanarak birden fazla varyasyon/diyalog sunar.
# Örnek: "<I enjoy missions...|I am trained with weapons...|I once infiltrated a base...>"
# Google Translate bu formatı bozar: pipe silinir, segmentler birleşir.
# Bu katman, çeviriden ÖNCE metni parçalara ayırır ve çeviriden SONRA
# geri birleştirir — böylece her segment bağımsız olarak çevrilir.
#
# Yaygın delimiter kalıpları:
#   <seg1|seg2|seg3>       — Angle-bracket + pipe (en yaygın)
#   seg1|seg2|seg3         — Bare pipe (wrapper olmadan)
#   seg1||seg2||seg3       — Double pipe
#
# NOT: Bu özellik sadece "metin" segmentleri ayrıştırır; Ren'Py text tag'leri
# ({b}, [var]) protect_renpy_syntax tarafından zaten korunuyor. Burada pipe
# ve dış sarmalayıcılar (<>) korunur.

# Regex: <...> wrapper içinde en az bir pipe — çok parçalı varyant metni
# Negatif lookbehind isteğe bağlı: [[< gibi escape'leri exclude etmek için
_DELIMITED_ANGLE_PIPE_RE = re.compile(
    r'^(?P<pre>[^<]*)(?P<open><)(?P<body>[^>]*\|[^>]*)(?P<close>>)(?P<post>[^>]*)$',
    re.DOTALL
)
# Bare pipe: wrapper yok, en az 2 segment, her segment anlamlı metin (3+ karakter)
_BARE_PIPE_RE = re.compile(
    r'^(?P<body>(?:[^|]{3,}\|){1,}[^|]{3,})$',
    re.DOTALL
)

# Regex: Tüm <seg1|seg2|...> gruplarını metinde bulur (multi-group desteği)
_ANGLE_PIPE_GROUP_RE = re.compile(r'<([^<>]*\|[^<>]*)>')


# ── Multi-Group Angle-Pipe Split (v2.7.5) ─────────────────────────────────────

def split_angle_pipe_groups(text: str) -> 'tuple[str, list[list[str]]] | None':
    """
    Multi-group destekli angle-pipe delimiter split (v2.7.5).
    
    Metindeki TÜM <seg1|seg2|...> gruplarını bulur ve placeholder-tabanlı
    template + grup listesine dönüştürür.
    
    Tek grup, çok grup ve çevreleyen metin dahil tüm kombinasyonları destekler:
      - ``<A|B|C>``                        → template=``[DGRP_0]``, groups=[[A,B,C]]
      - ``text <A|B> more text``           → template=``text [DGRP_0] more text``, groups=[[A,B]]
      - ``text <A|B> mid <C|D|E> end``     → template=``text [DGRP_0] mid [DGRP_1] end``
    
    Pipeline bu fonksiyonu çağırır:
      1. Template ayrı request olarak çevrilir ([DGRP_N] protect_renpy_syntax ile korunur)
      2. Her grubun segmentleri ayrı request olarak çevrilir
      3. rejoin_angle_pipe_groups() ile birleştirilir
    
    Returns:
        None — metin angle-pipe delimiter içermiyor veya geçersiz
        (template, groups) — template ``[DGRP_N]`` placeholder'lı şablon,
                            groups her grubun pipe-ayrılmış segment listesi
    """
    if not text or '<' not in text or '|' not in text or '>' not in text:
        return None
    
    matches = list(_ANGLE_PIPE_GROUP_RE.finditer(text))
    if not matches:
        return None
    
    groups: list[list[str]] = []
    for m in matches:
        body = m.group(1)
        segments = body.split('|')
        
        # En az 2 segment olmalı
        if len(segments) < 2:
            return None
        
        # Son segment boş olabilir (oyun scripti edge case: <A|B|>)
        # Boş son segment'i atla
        if segments and not segments[-1].strip():
            segments = segments[:-1]
        if len(segments) < 2:
            return None
        
        # Kalan segmentler boş olmamalı
        if not all(s.strip() for s in segments):
            return None
        
        # Saf sayı/sembol grup: çevrilmeye gerek yok ama YAPIYI koru
        # <0.1|0.02|0.005> gibi sayısal gruplar çevirilmez, ama template'e dahil edilir
        is_numeric_group = not any(any(c.isalpha() for c in s) for s in segments)
        
        if not is_numeric_group:
            # Herhangi bir segment kod benzeri ise tüm split'i iptal et
            if any(_is_code_like_segment(s.strip()) for s in segments):
                return None
        
        groups.append(([s.strip() for s in segments], is_numeric_group))
    
    # En az bir çevrilebilir (metin) grup olmalı
    if not any(not is_num for _, is_num in groups):
        return None
    
    # Template oluştur: metin gruplarını [DGRP_N] ile değiştir, sayısal grupları olduğu gibi bırak
    template = text
    offset = 0
    text_groups: list[list[str]] = []
    dgrp_idx = 0
    
    for i, m in enumerate(matches):
        segs, is_numeric = groups[i]
        if is_numeric:
            # Sayısal grup: template'de olduğu gibi bırak (placeholder yok)
            continue
        
        placeholder = f'[DGRP_{dgrp_idx}]'
        dgrp_idx += 1
        text_groups.append(segs)
        
        start = m.start() + offset
        end = m.end() + offset
        template = template[:start] + placeholder + template[end:]
        offset += len(placeholder) - (m.end() - m.start())
    
    return (template, text_groups)


def rejoin_angle_pipe_groups(
    translated_template: str,
    translated_groups: 'list[list[str]]'
) -> 'str | None':
    """
    Çevrilmiş template ve çevrilmiş grupları birleştirir (v2.7.5).
    
    Her [DGRP_N] placeholder'ını ilgili grubun <seg1|seg2|...> formatıyla
    değiştirir.
    
    Args:
        translated_template: Çevrilmiş şablon metin ([DGRP_N] placeholder'lı)
        translated_groups: Her grubun çevrilmiş segment listesi
    
    Returns:
        str — birleştirilmiş nihai metin
        None — placeholder kayboldu (çevirmen silmiş veya bozmuş)
    """
    result = translated_template
    
    for i, segments in enumerate(translated_groups):
        placeholder = f'[DGRP_{i}]'
        
        if placeholder not in result:
            return None  # Placeholder kaybolmuş — yapısal bozulma
        
        # Segmentlerde iç pipe/bracket kontrolü
        has_pipe = any('|' in seg for seg in segments)
        has_angle = any('<' in seg or '>' in seg for seg in segments)
        if has_pipe or has_angle:
            return None  # Segment bozulması — güvenli geri dönüş
        
        # Boş segment kontrolü
        if any(not seg.strip() for seg in segments):
            return None
        
        group_text = '<' + '|'.join(segments) + '>'
        result = result.replace(placeholder, group_text, 1)
    
    # Doubled placeholder koruması: GT tokeni çoğaltmışsa kalan [DGRP_ kalır
    if '[DGRP_' in result:
        return None
    
    return result


# ── False-Positive Detection Helpers ──────────────────────────────────────────

# Kod benzeri segment kalıpları (false positive göstergesi)
# v2.7.5: Minimum 2 char before dot to avoid A.I. abbreviation false positives
_CODE_DOT_RE = re.compile(r'[A-Za-z_]\w+\.\w+')        # obj.attr, GAME.mc.done (NOT A.I.)
_CODE_SNAKE_RE = re.compile(r'[a-z]+_[a-z_]+')          # snake_case tokens
_CODE_CALL_RE = re.compile(r'\w+\s*\(')                 # func(, call(
_CODE_ASSIGN_RE = re.compile(r'\w\s*[+\-*/]?=\s*\w')    # x = y, x += 1
_CODE_COMPARE_RE = re.compile(r'[<>=!]=|[<>]\s*\d')     # ==, !=, >=, < 5
_ALL_CAPS_RE = re.compile(r'^[A-Z][A-Z0-9_]{2,}$')      # CONSTANT, MC_NAME
# Ren'Py sözdizimi tokenleri: [variable], {tag}...{/tag} — bunlar KOD DEĞİL
_RENPY_BRACKET_RE = re.compile(r'\[[^\]]*\]|\{[^}]*\}')


def _strip_renpy_tokens(text: str) -> str:
    """Ren'Py sözdizimi tokenlerini ([var], {tag}) metinden çıkarır.
    Kod benzeri kontrolü yapılmadan önce çağrılır, böylece
    ``[player.name]`` gibi ifadeler yanlışlıkla 'kod' olarak algılanmaz.
    """
    return _RENPY_BRACKET_RE.sub(' ', text).strip()


def _is_code_like_segment(segment: str) -> bool:
    """
    Bir segment'in kod benzeri (çevrilmemesi gereken) içerik olup olmadığını
    tespit eder.
    
    Ren'Py sözdizimi tokenleri ([variable], {b}...{/b}) otomatik olarak
    çıkarılır — bunlar doğal dil metninin bir parçasıdır, kod değil.
    
    Kod göstergeleri:
      - Nokta gösterimi: ``GAME.mc``, ``player.quest_completed``
      - snake_case: ``quest_log``, ``mc_name``
      - Fonksiyon çağrısı: ``func()``, ``call(``
      - Atama/karşılaştırma: ``x = y``, ``a == b``
      - Tümü büyük harf sabit: ``INTRO``, ``MC``
      - Python/Ren'Py anahtar kelimeleri: ``if``, ``elif``, ``return``, ``True``
      - Dosya yolu: ``/path/to/file``, ``images/``
      
    Returns:
        True → kod benzeri (delimiter split'e dahil etme)
    """
    s = segment.strip()
    if not s:
        return False
    
    # Ren'Py sözdizimi tokenlerini çıkar (kod kontrolü öncesi)
    # "[player.name] was helpful" → "was helpful" (dot notation yanlış pozitif önlenir)
    s = _strip_renpy_tokens(s)
    if not s:
        return False
    
    # Dot notation (obj.attr, GAME.mc.done)
    if _CODE_DOT_RE.search(s):
        return True
    
    # Tam eşleşen ALL_CAPS sabitler (3+ karakter, tümü büyük)
    if _ALL_CAPS_RE.match(s):
        return True
    
    # snake_case tokenler (doğal dilde yaygın değil)
    if _CODE_SNAKE_RE.search(s):
        return True
    
    # Fonksiyon çağrısı
    if _CODE_CALL_RE.search(s):
        return True
    
    # Atama veya bileşik atama
    if _CODE_ASSIGN_RE.search(s):
        return True
    
    # Karşılaştırma/boolean operatörleri
    if _CODE_COMPARE_RE.search(s):
        return True
    
    # Python/Ren'Py anahtar kelime (segment tamamı tek keyword ise)
    _KEYWORDS = frozenset({
        'if', 'elif', 'else', 'return', 'pass', 'break', 'continue',
        'True', 'False', 'None', 'and', 'or', 'not', 'in', 'is',
        'def', 'class', 'import', 'from', 'with', 'as', 'try',
        'except', 'finally', 'raise', 'yield', 'lambda', 'del',
        'for', 'while', 'assert', 'global', 'nonlocal',
        'show', 'hide', 'scene', 'jump', 'call', 'menu', 'label',
        'init', 'python', 'define', 'default', 'screen', 'transform',
    })
    if s in _KEYWORDS:
        return True
    
    # Dosya yolu benzeri (v2.7.5: harf/alt çizgiyle devam eden yol ayırıcıları)
    # 10/20 gibi sayısal ifadeleri hariç tutar
    if re.search(r'[\\/][A-Za-z_]', s):
        return True
    
    # Yalnızca sayı/sembol (çevrilecek metin değil)
    if s.replace('.', '').replace('-', '').replace('+', '').isdigit():
        return True
    
    return False


def _is_natural_language_segment(segment: str, min_words: int = 2, min_len: int = 8) -> bool:
    """
    Bir segment'in doğal dil (çevrilmeye değer) metin olup olmadığını kontrol eder.
    
    Kontroller:
      - Minimum kelime sayısı (varsayılan 2)
      - Minimum karakter uzunluğu (varsayılan 8)
      - En az bir harf içermeli
      - Kod benzeri içerik olmamalı
      
    Returns:
        True → doğal dil, çevrilebilir
    """
    s = segment.strip()
    if not s:
        return False
    
    # Ren'Py tokenlerini çıkardıktan sonra kontrol et
    stripped = _strip_renpy_tokens(s)
    if not stripped:
        return False
    
    # Minimum uzunluk (Ren'Py tokenleri çıkarılmış halde)
    if len(stripped) < min_len:
        return False
    
    # En az bir alfabetik karakter olmalı
    if not any(c.isalpha() for c in stripped):
        return False
    
    # Kelime sayısı kontrolü (boşlukla ayrılmış gerçek kelimeler)
    words = stripped.split()
    if len(words) < min_words:
        return False
    
    # Kod benzeri değilse doğal dil kabul et
    return not _is_code_like_segment(s)


def _has_structural_integrity(segments: 'list[str]') -> bool:
    """
    Segment listesinin yapısal bütünlüğünü kontrol eder.
    Gerçek çevrilmeye değer diyalog varyantları mı yoksa tek kelimelik
    tanımlayıcı/etiket listeleri mi olduğunu ayırt eder.
    
    Returns:
        True → bütünlük tamam, delimiter split güvenli
    """
    if len(segments) < 2:
        return False
    
    # Segment sayısı çok fazlaysa (>15) muhtemelen veri listesi, çeviri değil
    if len(segments) > 15:
        return False
    
    # Her segment boş olmamalı
    if not all(s.strip() for s in segments):
        return False
    
    # Segment'lerin çoğunluğu doğal dil olmalı (en az %50)
    # min_words=2, min_len=8: Her segment en az 2 kelime ve 8 karakter olmalı
    natural_count = sum(1 for s in segments if _is_natural_language_segment(s, min_words=2, min_len=8))
    if natural_count < len(segments) * 0.5:
        return False
    
    # Hiçbir segmentte iç içe <> olmamalı
    for s in segments:
        s_stripped = s.strip()
        if '<' in s_stripped and '>' in s_stripped and '|' in s_stripped:
            return False
    
    return True


def split_delimited_text(text: str) -> 'tuple[list[str], str, str, str] | None':
    """
    Delimiter-aware metin bölme (v2.7.3 — Hardened).
    
    Eğer metin bilinen bir delimiter kalıbı içeriyorsa segmentlere ayırır.
    Kod benzeri string'ler, kısa tanımlayıcılar ve yapısal olarak riskli
    pattern'ler false-positive olarak filtrelenir.
    
    Returns:
        None — metin delimiter içermiyor veya false positive
        (segments, delimiter, prefix, suffix) — ayrıştırılmış parçalar
            segments: ['seg1', 'seg2', ...]
            delimiter: '|' (kullanılan ayırıcı karakter)
            prefix: '<' veya '' (dış açılış sarmalayıcı)
            suffix: '>' veya '' (dış kapanış sarmalayıcı)
    """
    if not text or '|' not in text:
        return None
    
    # ── Pattern 1: <seg1|seg2|seg3> (angle-bracket wrapping) ──────────────
    m = _DELIMITED_ANGLE_PIPE_RE.match(text)
    if m:
        pre = m.group('pre')
        body = m.group('body')
        post = m.group('post')
        segments = body.split('|')
        
        # En az 2 segment ve her biri boş olmamalı
        if len(segments) >= 2 and all(s.strip() for s in segments):
            # ── FALSE-POSITIVE FİLTRE (v2.7.3) ──
            # 1) Herhangi bir segment kod benzeri ise TÜM split'i iptal et
            if any(_is_code_like_segment(s) for s in segments):
                return None
            
            # 2) Yapısal bütünlük kontrolü
            if not _has_structural_integrity(segments):
                return None
            
            return (segments, '|', pre + '<', '>' + post)
    
    # ── Pattern 2: Bare pipe (seg1|seg2|seg3, wrapper yok) ────────────────
    # v2.7.5: Angle-bracket grupları varsa bare pipe'a düşme
    # (split_angle_pipe_groups tarafından ele alınmalı)
    stripped = text.strip()
    if _ANGLE_PIPE_GROUP_RE.search(stripped):
        return None  # Angle-pipe grup var — multi-group handler'a bırak
    
    if '|' in stripped and not stripped.startswith(('<', '{', '[')):
        m2 = _BARE_PIPE_RE.match(stripped)
        if m2:
            segments = stripped.split('|')
            # Ren'Py sözdizimi false-positive filtresi
            has_syntax = any(
                '{' in s or ('[' in s and ']' in s)
                for s in segments
            )
            if has_syntax:
                return None
            
            # ── FALSE-POSITIVE FİLTRE (v2.7.3) ──
            if any(_is_code_like_segment(s) for s in segments):
                return None
            
            if not _has_structural_integrity(segments):
                return None
            
            if len(segments) >= 2:
                prefix = text[:len(text) - len(text.lstrip())]  # Leading whitespace
                suffix = text[len(text.rstrip()):]  # Trailing whitespace
                return (segments, '|', prefix, suffix)
    
    return None


def rejoin_delimited_text(
    translated_segments: 'list[str]',
    delimiter: str,
    prefix: str,
    suffix: str,
    original_text: str = ''
) -> 'str | None':
    """
    Çevrilmiş segmentleri orijinal delimiter formatında geri birleştirir (v2.7.3).
    
    Birleştirme sonrası yapısal doğrulama yapar. Bozulma tespit edilirse
    ``None`` döndürür (çağıran kod orijinal metne geri dönmelidir).
    
    Args:
        translated_segments: Çevrilmiş metin parçaları
        delimiter: Orijinal ayırıcı ('|')
        prefix: Dış açılış ('<' veya '')
        suffix: Dış kapanış ('>' veya '')
        original_text: Orijinal çevrilmemiş metin (doğrulama için)
    
    Returns:
        str — birleştirilmiş, doğrulanmış metin
        None — yapısal bozulma tespit edildi, orijinale geri dön
    """
    body = delimiter.join(translated_segments)
    result = f"{prefix}{body}{suffix}"
    
    # ── POST-REJOIN YAPISAL DOĞRULAMA (v2.7.3) ──────────────────────────
    
    # 1) İç içe açılı parantez kontrolü: body kısmında çeviri kaynaklı <> olmamalı
    #    prefix='<' ve suffix='>' kullanan bir pattern'de body içinde ek < veya > 
    #    korrupt çıktı üretir (Ren'Py parse hatası kaynağı)
    if '<' in prefix or '>' in suffix:
        # Body kısmında iç içe <> veya | içeren yeni <...|...> pattern varsa → bozulma
        if '<' in body or '>' in body:
            return None
    
    # 2) Çevrilmiş segment'lerin hiçbiri pipe (delimiter) içermemeli
    #    Aksi halde pipe sayısı beklenenden fazla olur
    for seg in translated_segments:
        if delimiter in seg:
            return None
    
    # 3) Boş segment kontrolü: çevirmen bir segmenti tamamen silmiş olabilir
    if any(not seg.strip() for seg in translated_segments):
        return None
    
    # 4) Orijinal metin verilmişse karşılaştırmalı doğrulama
    if original_text:
        orig_pipe_count = original_text.count('|')
        result_pipe_count = result.count('|')
        # Pipe sayısı değişmişse → yapısal bozulma
        if orig_pipe_count != result_pipe_count:
            return None
    
    return result


# =============================================================================
# HTML WRAP PROTECTION
# =============================================================================
# Google Translate <span class="notranslate"> içindeki metni çevirmiyor.
# Bu yöntem placeholder değiştirmeden çok daha güvenilir.

# HTML koruma için regex (protect_renpy_syntax ile aynı pattern'leri kullanır)
# HTML koruma için regex (protect_renpy_syntax ile aynı pattern'leri kullanır - Shared Source)
HTML_PROTECT_RE = re.compile(_PROTECT_PATTERN_STR)


def protect_renpy_syntax_html(text: str) -> str:
    """
    Ren'Py sözdizimini HTML notranslate tag'leri ile korur.
    
    Google Translate <span class="notranslate">...</span> içindeki metni
    çevirmiyor. Bu yöntem placeholder değiştirmeden çok daha güvenilir.
    
    Args:
        text (str): Korunacak orijinal metin
        
    Returns:
        str: HTML tag'leri eklenmiş metin (Google'a gönderilecek)
    """
    if not text:
        return text
    
    def wrap_match(match: re.Match) -> str:
        """Her eşleşmeyi notranslate span'ı ile sar (Google resmi standartı)."""
        # translate="no" attribute - Google'ın resmi HTML5 standardı
        # class="notranslate" - eski yöntem, yedek olarak
        return f'<span translate="no" class="notranslate">{match.group(0)}</span>'
    
    return HTML_PROTECT_RE.sub(wrap_match, text)


def restore_renpy_syntax_html(text: str) -> str:
    """
    HTML notranslate tag'lerini temizler.
    
    Google'dan dönen metindeki <span class="notranslate">...</span>
    tag'lerini kaldırır ve içeriği korur.
    
    Args:
        text (str): Google'dan dönen HTML içerikli metin
        
    Returns:
        str: Temizlenmiş metin (orijinal tag'ler korunmuş)
    """
    if not text:
        return text
    
    # Pattern: <span class="notranslate">...</span>
    # Ayrıca Google'ın ekleyebileceği varyasyonları da yakala:
    # - <span class="notranslate">
    # - <span class='notranslate'>
    # - <SPAN class="notranslate">
    # - Boşluklu versiyonlar
    # Her iki formatı da destekle:
    # 1. <span translate="no" class="notranslate">...</span>
    # 2. <span class="notranslate">...</span>
    # 3. <span translate="no">...</span>
    pattern = re.compile(
        r'<span(?:\s+translate=["\']no["\'])?(?:\s+class=["\']notranslate["\'])?(?:\s+translate=["\']no["\'])?\s*>(.*?)</span>',
        re.IGNORECASE | re.DOTALL
    )
    
    result = pattern.sub(r'\1', text)
    
    # Google bazen sadece açılış tag'ini bırakabilir (hatalı durum)
    # Kalan orphan span tag'lerini de temizle
    result = re.sub(r'<span[^>]*translate=["\']no["\'][^>]*>', '', result, flags=re.IGNORECASE)
    result = re.sub(r'<span[^>]*class=["\']notranslate["\'][^>]*>', '', result, flags=re.IGNORECASE)
    result = re.sub(r'</span>', '', result, flags=re.IGNORECASE)
    
    # Google bazen fazladan HTML entity ekleyebilir, bunları da temizle
    result = result.replace('&lt;', '<').replace('&gt;', '>')
    result = result.replace('&amp;', '&').replace('&quot;', '"')
    
    return result


# =============================================================================
# XML PLACEHOLDER SYSTEM (LLM Optimized)
# =============================================================================
# LLM'ler (OpenAI, Gemini, vb.) en iyi XML benzeri yapıları korur.
# Bu nedenle XRPYX yerine <ph id="N">...</ph> formatı kullanıyoruz.


def protect_renpy_syntax_xml(text: str) -> Tuple[str, Dict[str, str]]:
    """
    LLM'ler için XML tabanlı koruma (XRPYX yerine).
    
    Format: <ph id="0">[variable]</ph>
    
    Bu format LLM'lerin "code-switching" yapmasını engeller ve
    taglerin içeriğini çevirmeden korumalarını sağlar.
    
    Args:
        text (str): Korunacak metin
        
    Returns:
        Tuple[str, Dict[str, str]]: (XML'li metin, placeholder map)
    """
    placeholders: Dict[str, str] = {}
    result_text = text
    
    counter = 0
    out_parts: List[str] = []
    last = 0
    
    for m in PROTECT_RE.finditer(result_text):
        start, end = m.start(), m.end()
        out_parts.append(result_text[last:start])
        
        token = m.group(0)
        
        # XML ID oluştur
        ph_id = str(counter)
        
        # <ph> tag'i oluştur
        # İçeriği de içinde tutuyoruz ki LLM bağlamı görsün ama dokunmasın
        xml_tag = f'<ph id="{ph_id}">{token}</ph>'
        
        # Map'e kaydet (id -> orijinal)
        placeholders[ph_id] = token
        
        out_parts.append(xml_tag)
        counter += 1
        last = end
        
    out_parts.append(result_text[last:])
    return ''.join(out_parts), placeholders


_ASCII_PH_RE = re.compile(r'__PH_([A-Za-z0-9]+)__')


def restore_renpy_syntax_xml(text: str, placeholders: Dict[str, str]) -> str:
    """
    XML taglerini temizler ve orijinalleri geri yükler.
    
    Regex ile <ph id="N">...</ph> yapılarını bulur ve map'teki
    orijinal değerle (id'ye göre) değiştirir.
    
    Args:
        text (str): XML içeren çevrilmiş metin
        placeholders (Dict[str, str]): id -> orijinal değer
        
    Returns:
        str: Temizlenmiş metin
    """
    if not text or not placeholders:
        return text
    
    # Innermost-first regex: matches <ph id="...">...</ph> where inner content
    # does NOT contain another unclosed '<ph' tag. Multi-pass loop ensures
    # any nested/adjacent XML tags are safely and completely unwrapped without leftover tags.
    ph_pattern_inner = re.compile(
        r'<ph\b[^>]*\bid\s*=\s*["\']?([A-Za-z0-9_]+)["\']?[^>]*>((?:(?!<ph\b).)*?)</\s*ph\s*>',
        re.IGNORECASE | re.DOTALL
    )
    
    def replacer(match):
        ph_id = match.group(1)
        # ID map'te varsa orijinali dön, yoksa match'i dön (integrity check yakalar)
        if ph_id in placeholders:
            return placeholders[ph_id]
        return match.group(0)
        
    cur = text
    for _ in range(5):
        next_cur = ph_pattern_inner.sub(replacer, cur)
        if next_cur == cur:
            break
        cur = next_cur

    # The AI prompts show __PH_0__-style examples. A model that answers
    # <ph id="0">...</ph> in that style must not cost the line its translation.
    cur = _ASCII_PH_RE.sub(lambda m: placeholders.get(m.group(1), m.group(0)), cur)
    return cur
