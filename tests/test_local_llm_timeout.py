"""Local model timeout: raised by the user's setting, longer on the built-in CPU runtime."""
from types import SimpleNamespace

from src.core.ai_translator import LocalLLMTranslator
from src.utils.constants import AI_LOCAL_CPU_TIMEOUT, AI_LOCAL_TIMEOUT


def cm(**kw):
    ts = dict(ai_timeout=120, local_llm_mode="external", local_llm_backend="vulkan")
    ts.update(kw)
    return SimpleNamespace(translation_settings=SimpleNamespace(**ts))


def test_default_keeps_the_local_floor():
    assert LocalLLMTranslator._local_timeout(cm()) == AI_LOCAL_TIMEOUT
    assert LocalLLMTranslator._local_timeout(None) == AI_LOCAL_TIMEOUT


def test_user_setting_can_raise_it():
    assert LocalLLMTranslator._local_timeout(cm(ai_timeout=300)) == 300


def test_user_setting_cannot_lower_it_below_the_floor():
    assert LocalLLMTranslator._local_timeout(cm(ai_timeout=30)) == AI_LOCAL_TIMEOUT


def test_builtin_cpu_runtime_gets_a_longer_floor():
    assert LocalLLMTranslator._local_timeout(cm(local_llm_mode="builtin", local_llm_backend="cpu")) == AI_LOCAL_CPU_TIMEOUT
    assert LocalLLMTranslator._local_timeout(cm(local_llm_mode="builtin", local_llm_backend="vulkan")) == AI_LOCAL_TIMEOUT
    assert LocalLLMTranslator._local_timeout(cm(local_llm_mode="external", local_llm_backend="cpu")) == AI_LOCAL_TIMEOUT


def test_translator_instance_uses_it():
    t = LocalLLMTranslator(config_manager=cm(local_llm_mode="builtin", local_llm_backend="cpu"))
    assert t._timeout == AI_LOCAL_CPU_TIMEOUT
