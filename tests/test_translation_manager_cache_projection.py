import asyncio

from src.core.translator import (
    TranslationEngine,
    TranslationManager,
    TranslationRequest,
    TranslationResult,
)


def test_translate_with_retry_projects_cross_engine_cache_hits_to_requested_engine() -> None:
    manager = TranslationManager()
    manager._cache[("libretranslate", "auto", "tr", "About")] = TranslationResult(
        original_text="About",
        translated_text="Hakkinda",
        source_lang="auto",
        target_lang="tr",
        engine=TranslationEngine.LIBRETRANSLATE,
        success=True,
    )

    request = TranslationRequest(
        text="About",
        source_lang="auto",
        target_lang="tr",
        engine=TranslationEngine.DEEPL,
        metadata={"original_text": "About"},
    )

    result = asyncio.run(manager.translate_with_retry(request))

    assert result.success is True
    assert result.engine == TranslationEngine.DEEPL
    assert result.metadata["cache_hit_type"] == "cross_engine"
    assert result.metadata["cache_source_engine"] == "libretranslate"
    assert ("deepl", "auto", "tr", "About") in manager._cache
    assert manager._cache[("deepl", "auto", "tr", "About")].engine == TranslationEngine.DEEPL


def test_translate_batch_projects_source_lang_fallback_cache_hits() -> None:
    manager = TranslationManager()
    manager._cache[("deepl", "en", "tr", "Save")] = TranslationResult(
        original_text="Save",
        translated_text="Kaydet",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.DEEPL,
        success=True,
    )

    request = TranslationRequest(
        text="Save",
        source_lang="auto",
        target_lang="tr",
        engine=TranslationEngine.DEEPL,
        metadata={"original_text": "Save"},
    )

    result = asyncio.run(manager.translate_batch([request]))[0]

    assert result.success is True
    assert result.engine == TranslationEngine.DEEPL
    assert result.source_lang == "auto"
    assert result.metadata["cache_hit_type"] == "source_lang_fallback"
    assert result.metadata["cache_source_lang"] == "en"
    assert ("deepl", "auto", "tr", "Save") in manager._cache


def test_translate_batch_routes_to_google_translator_without_name_error() -> None:
    from unittest.mock import AsyncMock
    from src.core.translator import GoogleTranslator

    manager = TranslationManager()
    gt = GoogleTranslator()
    mock_batch = AsyncMock(
        return_value=[
            TranslationResult(
                original_text="Hello",
                translated_text="Merhaba",
                source_lang="en",
                target_lang="tr",
                engine=TranslationEngine.GOOGLE,
                success=True,
            ),
            TranslationResult(
                original_text="World",
                translated_text="Dunya",
                source_lang="en",
                target_lang="tr",
                engine=TranslationEngine.GOOGLE,
                success=True,
            ),
        ]
    )
    gt.translate_batch = mock_batch
    manager.add_translator(TranslationEngine.GOOGLE, gt)

    reqs = [
        TranslationRequest("Hello", "en", "tr", TranslationEngine.GOOGLE),
        TranslationRequest("World", "en", "tr", TranslationEngine.GOOGLE),
    ]

    results = asyncio.run(manager.translate_batch(reqs))
    assert len(results) == 2
    assert results[0].translated_text == "Merhaba"
    assert results[1].translated_text == "Dunya"
    assert mock_batch.called


def test_translate_batch_routes_to_deepl_and_libre_without_name_error() -> None:
    from unittest.mock import AsyncMock
    from src.core.translator import DeepLTranslator

    manager = TranslationManager()
    dt = DeepLTranslator(api_key="mock_key")
    dt.translate_batch = AsyncMock(
        return_value=[
            TranslationResult(
                original_text="Hi",
                translated_text="Selam",
                source_lang="en",
                target_lang="tr",
                engine=TranslationEngine.DEEPL,
                success=True,
            )
        ]
    )
    manager.add_translator(TranslationEngine.DEEPL, dt)
    results = asyncio.run(
        manager.translate_batch([TranslationRequest("Hi", "en", "tr", TranslationEngine.DEEPL)])
    )
    assert len(results) == 1
    assert results[0].translated_text == "Selam"


def test_corrupt_cache_entries_rejected_from_cache_put() -> None:
    manager = TranslationManager()
    key = ("google", "en", "tr", "Hello")
    corrupt_result = TranslationResult(
        original_text="Hello",
        translated_text='Merhaba <ph id="0">leaked</ph>',
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    asyncio.run(manager._cache_put(key, corrupt_result))
    assert key not in manager._cache, "Corrupt translations with leaked placeholders must not be cached"

    clean_result = TranslationResult(
        original_text="Hello",
        translated_text="Merhaba",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    asyncio.run(manager._cache_put(key, clean_result))
    assert key in manager._cache
    assert manager._cache[key].translated_text == "Merhaba"


def test_corrupt_cache_entries_dropped_on_load(tmp_path) -> None:
    import json
    cache_file = tmp_path / "translation_cache.json"
    raw_data = {
        "google": {
            "en": {
                "tr": {
                    "Hello": "Merhaba",
                    "Bad Text 1": 'Bozuk <ph id="G0">tag</ph>',
                    "Bad Text 2": "Bozuk ⟦RLPH001_0⟧",
                    "Valid Text": "Gecerli",
                }
            }
        }
    }
    cache_file.write_text(json.dumps(raw_data, ensure_ascii=False), encoding="utf-8")

    manager = TranslationManager()
    manager.load_cache(str(cache_file))

    assert len(manager._cache) == 2
    assert ("google", "en", "tr", "Hello") in manager._cache
    assert ("google", "en", "tr", "Valid Text") in manager._cache
    assert ("google", "en", "tr", "Bad Text 1") not in manager._cache
    assert ("google", "en", "tr", "Bad Text 2") not in manager._cache


def test_cache_remove_and_update_text() -> None:
    manager = TranslationManager()
    key = ("google", "en", "tr", "Start")
    res = TranslationResult(
        original_text="Start",
        translated_text="{color=#fff}Basla{/color}",
        source_lang="en",
        target_lang="tr",
        engine=TranslationEngine.GOOGLE,
        success=True,
    )
    asyncio.run(manager._cache_put(key, res))
    assert key in manager._cache

    # Update with normalized text
    asyncio.run(manager.cache_update_text(key, "Basla"))
    assert manager._cache[key].translated_text == "Basla"

    # Remove key
    asyncio.run(manager.cache_remove(key))
    assert key not in manager._cache

