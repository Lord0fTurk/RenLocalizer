"""
Multi-Group Angle-Pipe Delimiter Tests (v2.7.5)

Tests for split_angle_pipe_groups() and rejoin_angle_pipe_groups()
which handle <seg1|seg2|seg3> patterns including multi-group strings,
surrounding text, short/single-word segments, and numeric groups.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.syntax_guard import (
    split_angle_pipe_groups,
    rejoin_angle_pipe_groups,
    split_delimited_text,
    _is_code_like_segment,
)


class TestSplitAnglePipeGroups:
    """split_angle_pipe_groups() birim testleri"""
    
    # ── Basic single-group ──────────────────────────────────────────────
    
    def test_single_group_basic(self):
        result = split_angle_pipe_groups('<Stay alert|Prepare your Vessel|Trade impacted>!')
        assert result is not None
        template, groups = result
        assert template == '[DGRP_0]!'
        assert groups == [['Stay alert', 'Prepare your Vessel', 'Trade impacted']]
    
    def test_single_group_with_surrounding_text(self):
        result = split_angle_pipe_groups('Pirate activity <near Asteroid Belt|In the Outer Zone> remains challenging!')
        assert result is not None
        template, groups = result
        assert template == 'Pirate activity [DGRP_0] remains challenging!'
        assert groups == [['near Asteroid Belt', 'In the Outer Zone']]
    
    def test_single_group_questions(self):
        result = split_angle_pipe_groups("<Anything new?|What's new?|What's up?>")
        assert result is not None
        template, groups = result
        assert template == '[DGRP_0]'
        assert len(groups[0]) == 3
    
    # ── Multi-group ─────────────────────────────────────────────────────
    
    def test_multi_group_basic(self):
        text = 'Gamma Ray eruptions <increasing|forecast|intensifying> <near Jumpgate|in Zone 25|in Zone 50>!'
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        assert template == 'Gamma Ray eruptions [DGRP_0] [DGRP_1]!'
        assert groups[0] == ['increasing', 'forecast', 'intensifying']
        assert groups[1] == ['near Jumpgate', 'in Zone 25', 'in Zone 50']
    
    def test_multi_group_both_at_edges(self):
        text = '<Demand|Price Level> for <Out Of System Goods|Tarakian Pets|Voronian Pets> remains high'
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        assert template == '[DGRP_0] for [DGRP_1] remains high'
        assert groups[0] == ['Demand', 'Price Level']
        assert groups[1] == ['Out Of System Goods', 'Tarakian Pets', 'Voronian Pets']
    
    # ── Short/single-word segments (previously rejected by structural integrity) ──
    
    def test_single_word_segments(self):
        result = split_angle_pipe_groups('<increasing|forecast|intensifying>')
        assert result is not None
        _, groups = result
        assert groups[0] == ['increasing', 'forecast', 'intensifying']
    
    def test_short_phrases(self):
        result = split_angle_pipe_groups("<Indeed.|You don't say.|Really?|Interesting...|Is that so?>")
        assert result is not None
        _, groups = result
        assert len(groups[0]) == 5
        assert groups[0][0] == 'Indeed.'
        assert groups[0][3] == 'Interesting...'
    
    # ── Numeric groups ──────────────────────────────────────────────────
    
    def test_mixed_numeric_and_text_groups(self):
        text = 'aligned the <quantum diffusors|navigation coils> to <0.1|0.02|0.005> below recommended levels'
        result = split_angle_pipe_groups(text)
        assert result is not None
        template, groups = result
        # Numeric group stays in template, text group gets placeholder
        assert '[DGRP_0]' in template
        assert '<0.1|0.02|0.005>' in template
        assert len(groups) == 1  # Only the text group
        assert groups[0] == ['quantum diffusors', 'navigation coils']
    
    def test_all_numeric_groups_returns_none(self):
        """When ALL groups are numeric, nothing to translate — skip"""
        text = 'exceeded the limit by <20|15|35> percent'
        result = split_angle_pipe_groups(text)
        # All groups are numeric → None (fall through to normal GT)
        assert result is None
    
    # ── Empty segment handling ──────────────────────────────────────────
    
    def test_trailing_empty_segment(self):
        """Game scripts sometimes have <A|B|> with trailing empty segment"""
        result = split_angle_pipe_groups('<Why not!|Would you, my Dear?|>')
        assert result is not None
        _, groups = result
        # Empty trailing segment should be stripped
        assert groups[0] == ['Why not!', 'Would you, my Dear?']
    
    def test_middle_empty_segment_rejected(self):
        """Empty segment in the middle = invalid"""
        result = split_angle_pipe_groups('<A||B>')
        assert result is None
    
    # ── Edge cases ──────────────────────────────────────────────────────
    
    def test_no_angle_brackets(self):
        assert split_angle_pipe_groups('Hello world') is None
    
    def test_no_pipe(self):
        assert split_angle_pipe_groups('<Hello world>') is None
    
    def test_empty_string(self):
        assert split_angle_pipe_groups('') is None
    
    def test_code_like_segments_rejected(self):
        """Code-like segments should cause rejection"""
        result = split_angle_pipe_groups('<GAME.mc|player.name>')
        assert result is None
    
    def test_keyword_segments_rejected(self):
        result = split_angle_pipe_groups('<if|else|return>')
        assert result is None
    
    # ── Escaped quotes (game edge case) ─────────────────────────────────
    
    def test_escaped_quotes_not_code(self):
        """Escaped quotes like \\\" should not trigger code detection"""
        text = '<\\"Yesss...|Aaahhh...|Indeed...|Oh yeah...>\\"'
        result = split_angle_pipe_groups(text)
        assert result is not None
        _, groups = result
        assert len(groups[0]) == 4
    
    # ── Ren'Py variable tokens ──────────────────────────────────────────
    
    def test_renpy_variables_not_code(self):
        """Ren'Py variables like [player.name] should NOT trigger code detection"""
        text = '<[C_SU_B]Heavenly Bodies[C_SU_E] employed bots|Station fees have gone up>'
        result = split_angle_pipe_groups(text)
        assert result is not None


class TestRejoinAnglePipeGroups:
    """rejoin_angle_pipe_groups() birim testleri"""
    
    def test_basic_rejoin(self):
        translated_template = 'Korsan faaliyeti [DGRP_0] zorlu olmaya devam ediyor!'
        translated_groups = [['Asteroit Kuşağı yakınında', 'Dış Bölgede']]
        result = rejoin_angle_pipe_groups(translated_template, translated_groups)
        assert result == 'Korsan faaliyeti <Asteroit Kuşağı yakınında|Dış Bölgede> zorlu olmaya devam ediyor!'
    
    def test_multi_group_rejoin(self):
        translated_template = 'Gama Işını patlamaları [DGRP_0] [DGRP_1]!'
        translated_groups = [
            ['artan', 'tahmin', 'yoğunlaşan'],
            ['Jumpgate yakınında', 'Bölge 25\'te', 'Bölge 50\'de']
        ]
        result = rejoin_angle_pipe_groups(translated_template, translated_groups)
        assert result is not None
        assert '<artan|tahmin|yoğunlaşan>' in result
        assert "<Jumpgate yakınında|Bölge 25'te|Bölge 50'de>" in result
    
    def test_turkish_word_order_swap(self):
        """GT may reorder groups for Turkish syntax — this is correct behavior"""
        translated_template = '[DGRP_1] için [DGRP_0] hala yüksek'
        translated_groups = [
            ['Talep', 'Fiyat Düzeyi'],
            ['Sistem Dışı Ürünler', 'Tarakian Evcil Hayvanları']
        ]
        result = rejoin_angle_pipe_groups(translated_template, translated_groups)
        assert result is not None
        # Group 1 should appear FIRST (Turkish word order)
        idx_g1 = result.index('<Sistem Dışı Ürünler')
        idx_g0 = result.index('<Talep')
        assert idx_g1 < idx_g0
    
    def test_placeholder_lost_returns_none(self):
        result = rejoin_angle_pipe_groups('Translated text without placeholder', [['seg1', 'seg2']])
        assert result is None
    
    def test_segment_with_pipe_returns_none(self):
        """Segments containing pipe = corruption"""
        result = rejoin_angle_pipe_groups('[DGRP_0]', [['seg1|seg2', 'seg3']])
        assert result is None
    
    def test_segment_with_angle_bracket_returns_none(self):
        result = rejoin_angle_pipe_groups('[DGRP_0]', [['<seg1', 'seg2>']])
        assert result is None
    
    def test_empty_segment_returns_none(self):
        result = rejoin_angle_pipe_groups('[DGRP_0]', [['seg1', '']])
        assert result is None


class TestCodeLikeSegmentFixes:
    """v2.7.5 false positive düzeltme testleri"""
    
    def test_ai_abbreviation_not_code(self):
        """A.I. is an abbreviation, not code"""
        assert _is_code_like_segment('employed illegal A.I. bots') is False
    
    def test_real_dot_notation_still_detected(self):
        """GAME.mc, player.name are still code"""
        assert _is_code_like_segment('GAME.mc') is True
        assert _is_code_like_segment('player.name') is True
    
    def test_escaped_quote_not_path(self):
        """Escaped quotes like \\" should not trigger file path detection"""
        assert _is_code_like_segment('\\"Yesss...') is False
    
    def test_real_path_still_detected(self):
        """Actual file paths should still be detected"""
        assert _is_code_like_segment('images/bg.png') is True
        assert _is_code_like_segment('path\\to\\file') is True


class TestDelimitedTextFallback:
    """split_delimited_text artık angle-bracket pattern'leri multi-group'a bırakmalı"""
    
    def test_angle_bracket_skipped_in_bare_pipe(self):
        """Multi-group strings should NOT fall to bare pipe"""
        text = 'Gamma Ray eruptions <increasing|forecast|intensifying> <near Jumpgate|in Zone 25>!'
        result = split_delimited_text(text)
        assert result is None  # Angle bracket present → skip bare pipe
    
    def test_bare_pipe_still_works(self):
        """Bare pipe without angle brackets should still work"""
        result = split_delimited_text('Option A|Option B|Option C')
        assert result is not None
        assert len(result[0]) == 3


class TestEndToEndFlow:
    """Tam akış simülasyonu: split → translate → rejoin"""
    
    def test_full_pipeline_multi_group(self):
        original = '<Demand|Price Level> for <Out Of System Goods|Tarakian Pets|Voronian Pets> remains high'
        
        # Step 1: Split
        result = split_angle_pipe_groups(original)
        assert result is not None
        template, groups = result
        
        # Step 2: Simulate translation
        # Template: "[DGRP_0] for [DGRP_1] remains high" → Turkish might reorder
        tr_template = '[DGRP_1] için [DGRP_0] hala yüksek'
        # Group 0: ['Demand', 'Price Level'] → ['Talep', 'Fiyat Düzeyi']
        # Group 1: ['Out Of System Goods', ...] → ['Sistem Dışı Ürünler', ...]
        tr_groups = [
            ['Talep', 'Fiyat Düzeyi'],
            ['Sistem Dışı Ürünler', 'Tarakian Evcil Hayvanları', 'Voronian Evcil Hayvanları']
        ]
        
        # Step 3: Rejoin
        final = rejoin_angle_pipe_groups(tr_template, tr_groups)
        assert final is not None
        
        # Verify structure
        assert '<Talep|Fiyat Düzeyi>' in final
        assert '<Sistem Dışı Ürünler|Tarakian Evcil Hayvanları|Voronian Evcil Hayvanları>' in final
        assert 'için' in final
        assert 'hala yüksek' in final
    
    def test_full_pipeline_single_group_with_surround(self):
        original = 'Pirate activity <near Asteroid Belt|In the Outer Zone> remains challenging!'
        
        result = split_angle_pipe_groups(original)
        assert result is not None
        template, groups = result
        assert template == 'Pirate activity [DGRP_0] remains challenging!'
        
        # Simulate: template and segments both get translated
        tr_template = 'Korsan faaliyeti [DGRP_0] zorlu olmaya devam ediyor!'
        tr_groups = [['Asteroit Kuşağı yakınında', 'Dış Bölgede']]
        
        final = rejoin_angle_pipe_groups(tr_template, tr_groups)
        assert final == 'Korsan faaliyeti <Asteroit Kuşağı yakınında|Dış Bölgede> zorlu olmaya devam ediyor!'
        # VERIFY: "Pirate activity" is now translated (was BUG 2 before!)
        assert 'Korsan faaliyeti' in final
        assert 'zorlu olmaya devam ediyor' in final


class TestDoubledPlaceholderGuard:
    """Doubled placeholder koruması: GT tokeni çoğaltırsa güvenli geri dönüş"""

    def test_doubled_placeholder_returns_none(self):
        """GT template'de [DGRP_0] çoğaltırsa → None"""
        # GT bazen tokeni 2 kere koyar
        tr_template = '[DGRP_0] and [DGRP_0] again [DGRP_1]'
        tr_groups = [['a', 'b'], ['c', 'd']]
        result = rejoin_angle_pipe_groups(tr_template, tr_groups)
        # İlk [DGRP_0] yerine koyulur ama ikincisi kalır → None
        assert result is None

    def test_normal_placeholders_still_work(self):
        """Normal (çoğaltılmamış) placeholder'lar hala çalışır"""
        tr_template = '[DGRP_0] için [DGRP_1] yüksek'
        tr_groups = [['Talep', 'Fiyat'], ['Ürünler', 'Hayvanlar']]
        result = rejoin_angle_pipe_groups(tr_template, tr_groups)
        assert result is not None
        assert '<Talep|Fiyat>' in result
        assert '<Ürünler|Hayvanlar>' in result

    def test_partial_placeholder_text_safe(self):
        """Metin içinde tesadüfen [DGRP_ geçerse (ama gerçek placeholder değilse)"""
        # Bu durumda tüm gerçek placeholder'lar yerine konmuş olmalı
        # Eğer kalıyorsa potansiyel tehlike → None
        tr_template = 'Bkz [DGRP_0] not: [DGRP_99]'
        tr_groups = [['a', 'b']]
        result = rejoin_angle_pipe_groups(tr_template, tr_groups)
        # [DGRP_99] kalmış → None
        assert result is None


class TestFilePathRegexFix:
    """File path detection fix: sayısal slash'ler artık FP değil"""

    def test_numeric_slash_not_detected(self):
        """10/20 gibi sayısal ifadeler dosya yolu değil"""
        assert _is_code_like_segment('10/20') is False

    def test_real_path_still_detected(self):
        """Gerçek dosya yolları hala algılanmalı"""
        assert _is_code_like_segment('images/bg_room.png') is True

    def test_backslash_path_detected(self):
        """Windows yolları hala algılanmalı"""
        assert _is_code_like_segment('game\\images\\bg.png') is True

    def test_escaped_quote_not_detected(self):
        """\\\" ile başlayan metin dosya yolu değil"""
        assert _is_code_like_segment('\\"Yesss...') is False

    def test_date_fraction_not_detected(self):
        """Tarih/kesir ifadeleri dosya yolu değil"""
        assert _is_code_like_segment('3/4') is False
        assert _is_code_like_segment('12/25') is False
