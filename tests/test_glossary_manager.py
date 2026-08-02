# -*- coding: utf-8 -*-
"""Unit tests for GlossaryManager."""

import pytest
from src.core.glossary_manager import GlossaryManager, preserve_case


def test_preserve_case():
    assert preserve_case("apple", "elma") == "elma"
    assert preserve_case("Apple", "elma") == "Elma"
    assert preserve_case("APPLE", "elma") == "ELMA"


def test_protect_terms():
    glossary = {"Lord": "Efendi", "Dark Lord": "Karanlık Efendi"}
    text = "The Dark Lord meets the Lord."
    
    protected, placeholders = GlossaryManager.protect_terms(text, glossary, xml_mode=False)
    
    # Dark Lord is longer, so it must be protected first
    assert len(placeholders) == 2
    assert "Dark Lord" not in protected
    assert "Lord" not in protected


def test_apply_glossary():
    glossary = {"Start": "Başla", "Load": "Yükle"}
    
    # Exact match test
    assert GlossaryManager.apply_glossary("Start", glossary, original_text="Start") == "Başla"
    
    # Text replacement test
    assert GlossaryManager.apply_glossary("Press Start to play.", glossary) == "Press Başla to play."
