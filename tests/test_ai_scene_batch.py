"""
Tests for Context-Aware Scene / Screenplay Batch Mode in AI Translator.
Validates scene building with speaker attribution, robust regex parsing,
and fallback behaviors.
"""
from src.core.ai_translator import (
    _build_scene_batch,
    _parse_scene_batch,
)


def test_build_scene_batch_with_speakers():
    texts = ["What are we doing here?", "Wait, it's dangerous!", "I know."]
    speakers = ["Alice", "Bob", "Alice"]
    result = _build_scene_batch(texts, speakers)

    expected = (
        "### SCENE START ###\n"
        "[0] Alice: What are we doing here?\n"
        "[1] Bob: Wait, it's dangerous!\n"
        "[2] Alice: I know.\n"
        "### SCENE END ###"
    )
    assert result == expected


def test_build_scene_batch_without_speakers():
    texts = ["Line one", "Line two"]
    result = _build_scene_batch(texts, None)

    expected = (
        "### SCENE START ###\n"
        "[0] Line one\n"
        "[1] Line two\n"
        "### SCENE END ###"
    )
    assert result == expected


def test_parse_scene_batch_clean():
    response = (
        "[0] Burada ne yapiyoruz?\n"
        "[1] Bekle, burasi tehlikeli!\n"
        "[2] Biliyorum."
    )
    parsed = _parse_scene_batch(response, 3)
    assert parsed == ["Burada ne yapiyoruz?", "Bekle, burasi tehlikeli!", "Biliyorum."]


def test_parse_scene_batch_strips_echoed_speaker():
    response = (
        "[0] Alice: Burada ne yapiyoruz?\n"
        "[1] Bob: Bekle, burasi tehlikeli!\n"
        "[2] Alice: Biliyorum."
    )
    speakers = ["Alice", "Bob", "Alice"]
    parsed = _parse_scene_batch(response, 3, expected_speakers=speakers)
    assert parsed == ["Burada ne yapiyoruz?", "Bekle, burasi tehlikeli!", "Biliyorum."]


def test_parse_scene_batch_tolerant_formats():
    response = (
        "0. Ilk diyalog\n"
        "[1]: Ikinci diyalog\n"
        "(2) Ucuncu diyalog\n"
        "3 - Dorduncu diyalog"
    )
    parsed = _parse_scene_batch(response, 4)
    assert parsed == ["Ilk diyalog", "Ikinci diyalog", "Ucuncu diyalog", "Dorduncu diyalog"]


def test_parse_scene_batch_markdown_fence():
    response = (
        "```text\n"
        "[0] Selam!\n"
        "[1] Nasilsin?\n"
        "```"
    )
    parsed = _parse_scene_batch(response, 2)
    assert parsed == ["Selam!", "Nasilsin?"]


def test_parse_scene_batch_missing_lines():
    # Only line 0 and line 2 returned, line 1 is missing
    response = (
        "[0] Ilk satir\n"
        "[2] Ucuncu satir"
    )
    parsed = _parse_scene_batch(response, 3)
    assert parsed == ["Ilk satir", None, "Ucuncu satir"]


def test_parse_scene_batch_preserves_renpy_tokens():
    response = (
        "[0] Selam __PH_0__, oyuna hos geldin!\n"
        "[1] {b}Dikkat!{/b} [player_name] yaklasiyor."
    )
    parsed = _parse_scene_batch(response, 2)
    assert parsed == [
        "Selam __PH_0__, oyuna hos geldin!",
        "{b}Dikkat!{/b} [player_name] yaklasiyor.",
    ]


def test_translate_batch_scene_mode_integration(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from src.core.ai_translator import OpenAITranslator
    from src.core.translator import TranslationRequest, TranslationEngine
    from src.utils.config import ConfigManager

    cfg = ConfigManager()
    cfg.translation_settings.ai_batch_format = "scene"
    cfg.translation_settings.ai_scene_batch_size = 5

    tr = OpenAITranslator(api_key="fake_key", config_manager=cfg)

    # Mock _call_api
    fake_scene_response = (
        "[0] Burada ne yapiyoruz?\n"
        "[1] Bekle, burasi tehlikeli!"
    )
    tr._call_api = AsyncMock(return_value=fake_scene_response)

    reqs = [
        TranslationRequest(text="What are we doing here?", source_lang="en", target_lang="tr", engine=TranslationEngine.OPENAI, metadata={"character": "Alice"}),
        TranslationRequest(text="Wait, it's dangerous!", source_lang="en", target_lang="tr", engine=TranslationEngine.OPENAI, metadata={"character": "Bob"}),
    ]

    results = asyncio.run(tr.translate_batch(reqs))
    assert len(results) == 2
    assert results[0].translated_text == "Burada ne yapiyoruz?"
    assert results[1].translated_text == "Bekle, burasi tehlikeli!"

    # Verify that the user prompt contained the screenplay format
    called_user_content = tr._call_api.call_args[0][1]
    assert "### SCENE START ###" in called_user_content
    assert "[0] Alice: What are we doing here?" in called_user_content
    assert "[1] Bob: Wait, it's dangerous!" in called_user_content

