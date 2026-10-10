# -*- coding: utf-8 -*-
"""
RenLocalizer CLI Main Module
Modern terminal interface powered by Rich
"""

import sys
import atexit
import os
import argparse
import signal
import json
import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSlot

from src.utils.config import ConfigManager
from src.core.translation_pipeline import TranslationPipeline, PipelineResult, PipelineStage
from src.core.translator import TranslationManager, TranslationEngine, PseudoTranslator
from src.core.local_llm_server import LlamaServerManager, cleanup_stale_server
from src.core.proxy_manager import ProxyManager
from src.version import VERSION

# Rich Library
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TaskProgressColumn, MofNCompleteColumn
    from rich.columns import Columns
    from rich.align import Align
    from rich.rule import Rule
    from rich import box
    from rich.traceback import install as install_rich_traceback
    install_rich_traceback(show_locals=False, width=100)
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

logger = logging.getLogger(__name__)

# UTF-8 stdout
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception as e:
    logger.debug("Failed to reconfigure stdout/stderr encoding: %s", e)

if RICH_AVAILABLE:
    console = Console(highlight=False)
else:
    class _FallbackConsole:
        def print(self, *args, **kwargs):
            text = ' '.join(str(a) for a in args)
            print(text)
        def rule(self, title="", **kwargs):
            print(f"\n{'─' * 20} {title} {'─' * 20}")
        def input(self, prompt=""):
            return input(prompt)
    console = _FallbackConsole()

# Theme
BRAND_PRIMARY = "bright_magenta"
BRAND_SECONDARY = "bright_cyan"
BRAND_ACCENT = "bright_yellow"
BRAND_SUCCESS = "bright_green"
BRAND_ERROR = "bright_red"
BRAND_WARNING = "yellow"
BRAND_DIM = "dim white"

ENGINES = [
    ("google",         "Google Translate",  "🌐", "Free — 13 mirror fallback"),
    ("bing",           "Bing / MS Edge",    "🪟", "Free — no API key, Google fallback"),
    ("openai",         "OpenAI (GPT)",      "🤖", "API key required"),
    ("deepseek",       "DeepSeek",          "🔮", "API key required — OpenAI compatible"),
    ("gemini",         "Google Gemini",     "✨", "API key required"),
    ("local_llm",      "Local LLM",         "🏠", "Ollama / LM Studio / built-in GGUF"),
    ("libretranslate", "LibreTranslate",    "🔓", "Self-hosted — Docker/Local"),
    ("custom",         "Custom Endpoint",   "🔗", "Any LibreTranslate-compatible API"),
]

LANGUAGES = [
    ("tr", "Turkish",    "🇹🇷"),
    ("en", "English",    "🇬🇧"),
    ("fr", "French",     "🇫🇷"),
    ("de", "German",     "🇩🇪"),
    ("es", "Spanish",    "🇪🇸"),
    ("ru", "Russian",    "🇷🇺"),
    ("ja", "Japanese",   "🇯🇵"),
    ("ko", "Korean",     "🇰🇷"),
    ("zh", "Chinese",    "🇨🇳"),
    ("pt", "Portuguese", "🇵🇹"),
    ("ar", "Arabic",     "🇸🇦"),
    ("it", "Italian",    "🇮🇹"),
    ("fa", "Persian",    "🇮🇷"),
]

# Owns the optional built-in llama-server child process (GGUF runner); the
# atexit hook in run_translate_command guarantees it is not left behind.
_LLAMA_SERVER = LlamaServerManager()

ENGINE_MAP = {
    "google": TranslationEngine.GOOGLE,
    "bing": TranslationEngine.BING,
    "openai": TranslationEngine.OPENAI,
    "deepseek": TranslationEngine.OPENAI,
    "gemini": TranslationEngine.GEMINI,
    "local_llm": TranslationEngine.LOCAL_LLM,
    "libretranslate": TranslationEngine.LIBRETRANSLATE,
    "custom": TranslationEngine.CUSTOM,
}


# ============================================================
# UI Helpers
# ============================================================

def print_banner():
    if not RICH_AVAILABLE:
        print(f"\n{'=' * 60}")
        print(f"       RenLocalizer CLI v{VERSION}")
        print(f"       Ren'Py Game Translation Tool")
        print(f"{'=' * 60}")
        return

    banner_lines = [
        "╔═══════════════════════════════════════════════════╗",
        "║                                                   ║",
        "║   ██████╗ ███████╗███╗   ██╗                      ║",
        "║   ██╔══██╗██╔════╝████╗  ██║                      ║",
        "║   ██████╔╝█████╗  ██╔██╗ ██║                      ║",
        "║   ██╔══██╗██╔══╝  ██║╚██╗██║                      ║",
        "║   ██║  ██║███████╗██║ ╚████║  LOCALIZER           ║",
        "║   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝                     ║",
        "║                                                   ║",
        f"║   CLI v{VERSION:<10s}  Ren'Py Translation Tool     ║",
        "║                                                   ║",
        "╚═══════════════════════════════════════════════════╝",
    ]

    gradient_colors = [
        "rgb(180,80,255)", "rgb(160,90,255)", "rgb(140,100,255)",
        "rgb(120,120,255)", "rgb(100,140,255)", "rgb(80,160,255)",
        "rgb(60,180,255)", "rgb(80,200,240)", "rgb(100,220,220)",
        "rgb(120,240,200)", "rgb(100,220,220)", "rgb(80,200,240)",
    ]

    text = Text()
    for i, line in enumerate(banner_lines):
        color = gradient_colors[i % len(gradient_colors)]
        text.append(line + "\n", style=color)
    console.print(Align.center(text))


def print_section_header(title: str, icon: str = ""):
    if RICH_AVAILABLE:
        label = f"{icon}  {title}" if icon else title
        console.print()
        console.rule(f"[bold {BRAND_PRIMARY}]{label}[/]", style=BRAND_DIM)
        console.print()
    else:
        print(f"\n{'─' * 20} {icon} {title} {'─' * 20}\n")


def print_key_value(key: str, value: str, icon: str = ""):
    prefix = f"{icon} " if icon else "  "
    if RICH_AVAILABLE:
        console.print(f"  {prefix}[{BRAND_DIM}]{key}:[/]  [{BRAND_SECONDARY}]{value}[/]")
    else:
        print(f"  {prefix}{key}: {value}")


def print_success(message: str):
    if RICH_AVAILABLE:
        console.print(f"  [bold {BRAND_SUCCESS}]✅ {message}[/]")
    else:
        print(f"  ✅ {message}")


def print_error(message: str):
    if RICH_AVAILABLE:
        console.print(f"  [bold {BRAND_ERROR}]❌ {message}[/]")
    else:
        print(f"  ❌ {message}")


def print_warning(message: str):
    if RICH_AVAILABLE:
        console.print(f"  [{BRAND_WARNING}]⚠  {message}[/]")
    else:
        print(f"  ⚠ {message}")


def print_info(message: str):
    if RICH_AVAILABLE:
        console.print(f"  [{BRAND_SECONDARY}]ℹ  {message}[/]")
    else:
        print(f"  ℹ {message}")


def get_user_input(prompt: str, default: str = "") -> str:
    if default:
        if RICH_AVAILABLE:
            result = console.input(f"  [{BRAND_PRIMARY}]❯[/] {prompt} [{BRAND_DIM}][{default}][/]: ").strip()
        else:
            result = input(f"  ❯ {prompt} [{default}]: ").strip()
        return result if result else default
    else:
        if RICH_AVAILABLE:
            return console.input(f"  [{BRAND_PRIMARY}]❯[/] {prompt}: ").strip()
        else:
            return input(f"  ❯ {prompt}: ").strip()


def print_menu(title: str, options: list, show_back: bool = True, icons: list = None) -> int:
    if RICH_AVAILABLE:
        console.print(f"\n  [bold {BRAND_PRIMARY}]{title}[/]")
        console.print(f"  [dim]{'─' * 44}[/]")
        for i, option in enumerate(options, 1):
            icon = icons[i-1] if icons and i-1 < len(icons) else "•"
            console.print(f"    [{BRAND_ACCENT}][{i}][/]  {icon}  {option}")
        if show_back:
            console.print(f"    [{BRAND_DIM}][0]  ←  Back[/]")
        console.print()
    else:
        print(f"\n  {title}")
        print(f"  {'─' * 44}")
        for i, option in enumerate(options, 1):
            print(f"    [{i}] {option}")
        if show_back:
            print(f"    [0] Back")
        print()

    while True:
        try:
            choice = get_user_input("Your choice")
            if choice == '0' and show_back:
                return 0
            num = int(choice)
            if 1 <= num <= len(options):
                return num
            print_warning("Invalid choice — please try again")
        except ValueError:
            print_warning("Please enter a number")


def build_summary_panel(data: dict, title: str = "Summary") -> None:
    if RICH_AVAILABLE:
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2), expand=False)
        table.add_column("Key", style=BRAND_DIM, min_width=18)
        table.add_column("Value", style=f"bold {BRAND_SECONDARY}")
        for key, value in data.items():
            table.add_row(key, str(value))
        panel = Panel(table, title=f"[bold {BRAND_PRIMARY}]{title}[/]", border_style=BRAND_DIM, padding=(1, 2))
        console.print(panel)
    else:
        print(f"\n  {title}")
        print(f"  {'─' * 40}")
        for key, value in data.items():
            print(f"    {key:<18s} {value}")
        print()


def clear_screen():
    if RICH_AVAILABLE:
        console.clear()
    else:
        os.system('cls' if os.name == 'nt' else 'clear')


# ============================================================
# CliHandler — Pipeline Signal Receiver
# ============================================================

class CliHandler(QObject):
    def __init__(self, pipeline: TranslationPipeline, verbose: bool = False):
        super().__init__()
        self.pipeline = pipeline
        self.verbose = verbose
        self._progress = None
        self._progress_task = None
        self._start_time = time.time()
        self.succeeded = False

        self.pipeline.stage_changed.connect(self.on_stage_changed)
        self.pipeline.progress_updated.connect(self.on_progress_updated)
        self.pipeline.log_message.connect(self.on_log_message)
        self.pipeline.finished.connect(self.on_finished)
        self.pipeline.show_warning.connect(self.on_warning)

    @pyqtSlot(str, str)
    def on_stage_changed(self, stage: str, message: str):
        if self._progress is not None:
            try:
                self._progress.stop()
            except Exception as e:
                logger.debug("Failed to stop CLI progress bar on stage change: %s", e)
            self._progress = None
            self._progress_task = None

        if RICH_AVAILABLE:
            console.print()
            console.rule(f"[bold {BRAND_ACCENT}]⚡ {message}[/]", style=BRAND_DIM)
        else:
            print(f"\n>> STAGE: {message}")

    @pyqtSlot(int, int, str)
    def on_progress_updated(self, current: int, total: int, text: str):
        if total <= 0:
            return
        if RICH_AVAILABLE:
            if self._progress is None:
                self._progress = Progress(
                    SpinnerColumn("dots", style=BRAND_PRIMARY),
                    TextColumn("[bold]{task.description}[/]", justify="left"),
                    BarColumn(bar_width=30, style=BRAND_DIM, complete_style=BRAND_PRIMARY, finished_style=BRAND_SUCCESS),
                    MofNCompleteColumn(), TaskProgressColumn(), TimeRemainingColumn(),
                    console=console, transient=False,
                )
                self._progress.start()
                self._progress_task = self._progress.add_task(text[:60], total=total, completed=current)
            else:
                self._progress.update(self._progress_task, completed=current, total=total, description=text[:60])
        else:
            pct = int((current / total) * 100) if total > 0 else 0
            sys.stdout.write(f"\rProgress: [{current}/{total}] {pct}%")
            sys.stdout.flush()

    @pyqtSlot(str, str)
    def on_log_message(self, level: str, message: str):
        if not self.verbose and level in ("info", "debug"):
            return
        if RICH_AVAILABLE:
            level_styles = {"info": (BRAND_DIM, "ℹ"), "success": (BRAND_SUCCESS, "✅"),
                            "warning": (BRAND_WARNING, "⚠"), "error": (BRAND_ERROR, "❌")}
            style, icon = level_styles.get(level, (BRAND_DIM, "•"))
            console.print(f"  [{style}]{icon} {message}[/]")
        else:
            print(f"\n[{level.upper()}] {message}")

    @pyqtSlot(str, str)
    def on_warning(self, title: str, message: str):
        if RICH_AVAILABLE:
            console.print(Panel(f"[{BRAND_WARNING}]{message}[/]", title=f"[bold {BRAND_WARNING}]⚠ {title}[/]",
                                border_style=BRAND_WARNING, padding=(0, 2)))
        else:
            print(f"\n[WARNING] {title}: {message}")

    @pyqtSlot(object)
    def on_finished(self, result: PipelineResult):
        if self._progress is not None:
            try:
                self._progress.stop()
            except Exception as e:
                logger.debug("Failed to stop CLI progress bar on finish: %s", e)
            self._progress = None

        self.succeeded = bool(result.success)
        elapsed = time.time() - self._start_time
        elapsed_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        console.print()

        if result.success:
            if RICH_AVAILABLE:
                result_table = Table(show_header=False, box=box.ROUNDED, padding=(0, 2))
                result_table.add_column("", style=BRAND_DIM, min_width=16)
                result_table.add_column("", style=f"bold {BRAND_SECONDARY}")
                if result.stats:
                    result_table.add_row("Total items", str(result.stats.get('total', 0)))
                    result_table.add_row("Translated", str(result.stats.get('translated', 0)))
                    result_table.add_row("Untranslated", str(result.stats.get('untranslated', 0)))
                result_table.add_row("Duration", elapsed_str)
                panel = Panel(result_table, title=f"[bold {BRAND_SUCCESS}]✅ Translation Complete[/]",
                              subtitle=f"[{BRAND_DIM}]{result.message}[/]", border_style=BRAND_SUCCESS, padding=(1, 2))
                console.print(panel)
            else:
                print(f"\n{'=' * 60}\nSUCCESS\n{result.message}\nDuration: {elapsed_str}\n{'=' * 60}")
        else:
            if RICH_AVAILABLE:
                panel = Panel(f"[bold]{result.message}[/]",
                              title=f"[bold {BRAND_ERROR}]❌ Translation Failed[/]",
                              border_style=BRAND_ERROR, padding=(1, 2))
                console.print(panel)
            else:
                print(f"\n{'=' * 60}\nFAILED\n{result.message}\n{'=' * 60}")

        QCoreApplication.quit()


# ============================================================
# Config & Engine Setup
# ============================================================

def load_config_override(config_path: str) -> dict:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print_error(f"Loading config file: {e}")
        return {}


def setup_engines(config: ConfigManager, engine_id: str, lt_url: str = "", lt_key: str = ""):
    """Setup translation engines (Google always as fallback)."""
    proxy_manager = ProxyManager()
    proxy_manager.configure_from_settings(config.proxy_settings)
    translation_manager = TranslationManager(proxy_manager, config)

    from src.core.translator import GoogleTranslator
    google = GoogleTranslator(proxy_manager=proxy_manager, config_manager=config)
    translation_manager.add_translator(TranslationEngine.GOOGLE, google)

    engine = ENGINE_MAP.get(engine_id, TranslationEngine.GOOGLE)
    if engine == TranslationEngine.GOOGLE:
        return config, translation_manager

    try:
        if engine == TranslationEngine.GEMINI:
            from src.core.ai_translator import GeminiTranslator
            t = GeminiTranslator(
                api_key=config.api_keys.gemini_api_key or "",
                proxy_manager=proxy_manager, config_manager=config,
            )
            # Safety-blocked / quota / placeholder-broken items go to Google (same as GUI).
            t.set_fallback_translator(google)
            translation_manager.add_translator(TranslationEngine.GEMINI, t)
        elif engine in (TranslationEngine.OPENAI, TranslationEngine.LOCAL_LLM):
            from src.core.ai_translator import OpenAITranslator, LocalLLMTranslator, DeepSeekTranslator
            if engine == TranslationEngine.OPENAI:
                # OpenAITranslator does not read the key from config itself; the
                # CLI used to send "none" so OpenAI/DeepSeek could never work.
                api_key = config.api_keys.openai_api_key or ""
                base_url = getattr(config.translation_settings, "openai_base_url", "") or ""
                if engine_id == "deepseek" or "deepseek" in base_url.lower():
                    t = DeepSeekTranslator(api_key=api_key, proxy_manager=proxy_manager, config_manager=config)
                else:
                    t = OpenAITranslator(api_key=api_key, proxy_manager=proxy_manager, config_manager=config)
                translation_manager.add_translator(TranslationEngine.OPENAI, t)
            else:
                t = LocalLLMTranslator(proxy_manager=proxy_manager, config_manager=config)
                # Built-in GGUF mode: run llama-server ourselves (no Ollama/LM Studio).
                if getattr(config.translation_settings, "local_llm_mode", "external") == "builtin":
                    ts = config.translation_settings
                    base_url = _LLAMA_SERVER.start(
                        model_path=getattr(ts, "local_llm_gguf_path", ""),
                        user_path=getattr(ts, "local_llm_server_path", ""),
                        backend=getattr(ts, "local_llm_backend", "vulkan"),
                        gpu_layers=getattr(ts, "local_llm_gpu_layers", -1),
                        ctx_size=getattr(ts, "local_llm_ctx_size", 4096),
                        parallel=max(1, int(getattr(ts, "ai_concurrency", 2) or 2)),
                        port=getattr(ts, "local_llm_server_port", 0),
                    )
                    t._base_url = base_url
                    t._client = None  # rebuilt lazily against the new URL
                    print_success(f"Built-in llama-server ready: {base_url}")
                translation_manager.add_translator(TranslationEngine.LOCAL_LLM, t)
        elif engine == TranslationEngine.BING:
            from src.core.translator import BingTranslator
            t = BingTranslator(proxy_manager=proxy_manager, config_manager=config)
            t.set_fallback_translator(google)
            translation_manager.add_translator(TranslationEngine.BING, t)
        elif engine in (TranslationEngine.LIBRETRANSLATE, TranslationEngine.CUSTOM):
            from src.core.translator import LibreTranslateTranslator
            base_url = lt_url or getattr(config.translation_settings, "libretranslate_url", "http://localhost:5000")
            api_key = lt_key or getattr(config.translation_settings, "libretranslate_api_key", "")
            t = LibreTranslateTranslator(base_url=base_url, api_key=api_key,
                                         proxy_manager=proxy_manager, config_manager=config)
            translation_manager.add_translator(engine, t)
    except Exception as e:
        print_warning(f"Engine {engine_id} setup failed, using Google fallback: {e}")

    return config, translation_manager


# ============================================================
# Translate Command
# ============================================================

def run_translate_command(args) -> int:
    """Run translation pipeline."""
    print_banner()
    atexit.register(_LLAMA_SERVER.stop)
    cleanup_stale_server()  # reclaim a llama-server left by a crashed run

    input_path = os.path.abspath(args.input_path) if args.input_path else None
    if not input_path or not os.path.exists(input_path):
        print_error(f"Path not found: {input_path}")
        return 1
    from src.utils.path_manager import unwrap_mac_app
    input_path = unwrap_mac_app(input_path)  # Game.app → Contents/Resources/autorun

    config = ConfigManager()
    config_path = getattr(args, 'config', None)
    if config_path:
        if not os.path.exists(config_path):
            print_error(f"Config file not found: {config_path}")
            return 1
        override = load_config_override(config_path)
        for section, values in override.items():
            if hasattr(config, section) and isinstance(values, dict):
                for key, val in values.items():
                    setattr(getattr(config, section), key, val)

    engine_id = args.engine
    ts = config.translation_settings
    _apply_ai_overrides(config, engine_id, args)

    # Same language handling as the GUI: "tr" / "Turkish" -> Ren'Py's "turkish",
    # so the output lands in tl/turkish instead of a tl/tr folder no game uses.
    target_lang = config.normalize_renpy_language_code(args.target_lang)
    source_lang = args.source_lang or "auto"
    ts.target_language = target_lang
    ts.source_language = source_lang
    ts.selected_engine = engine_id

    # Every pipeline switch comes from the user's settings (as in the GUI);
    # command-line flags override them. These were hard-coded off before, so
    # .rpa archives were never extracted (issue #20) and .rpyc never read.
    auto_unren = _flag_or(args, 'extract_rpa', getattr(config.app_settings, 'unren_auto_download', True))
    include_rpyc = _flag_or(args, 'rpyc', getattr(ts, 'enable_rpyc_reader', True))
    include_deep_scan = bool(getattr(args, 'deep_scan', False)) or bool(getattr(ts, 'enable_deep_scan', False))
    if include_deep_scan:
        ts.enable_deep_scan = True
    use_proxy = bool(getattr(config.proxy_settings, 'enabled', False))
    ts.activate_language_on_launch = _flag_or(args, 'language_init', getattr(ts, 'activate_language_on_launch', True))
    is_tl_mode = bool(getattr(args, 'tl', False)) or _looks_like_tl_folder(input_path)

    print_section_header("Translation Settings", "⚙")
    print_key_value("Input", input_path, "📁")
    print_key_value("Mode", "existing tl/ folder" if is_tl_mode else "full game", "🧭")
    print_key_value("Engine", engine_id, "⚡")
    print_key_value("Source", source_lang, "🌍")
    print_key_value("Target", target_lang, "🌍")
    if not is_tl_mode:
        print_key_value("Extract .rpa", "on" if auto_unren else "off", "📦")
        print_key_value("Read .rpyc", "on" if include_rpyc else "off", "🧩")
    print_key_value("Activate language in game", "on" if ts.activate_language_on_launch else "off (tl/ files only)", "🏳")
    if include_deep_scan:
        print_key_value("Deep scan", "on", "🔍")

    lt_url = getattr(args, 'lt_url', '')
    lt_key = getattr(args, 'lt_key', '')
    if engine_id in ("libretranslate", "custom"):
        print_key_value("Endpoint", lt_url or "http://localhost:5000", "🔗")

    config, translation_manager = setup_engines(config, engine_id, lt_url, lt_key)

    print_section_header("Running Translation", "🚀")
    console.print()

    engine = ENGINE_MAP.get(engine_id, TranslationEngine.GOOGLE)
    pipeline = TranslationPipeline(config, translation_manager)
    handler = CliHandler(pipeline, verbose=getattr(args, 'verbose', False))
    pipeline.configure(
        game_exe_path=input_path, target_language=target_lang, source_language=source_lang,
        engine=engine, auto_unren=auto_unren, use_proxy=use_proxy,
        include_deep_scan=include_deep_scan,
        include_rpyc=include_rpyc,
        is_tl_mode=is_tl_mode,
    )

    from src.core.translation_pipeline import PipelineWorker
    worker = PipelineWorker(pipeline)
    worker.start()

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    app.exec()
    worker.wait(5000)
    # Non-zero on failure so scripts and CI can tell (it was always 0).
    return 0 if handler.succeeded else 1


def _flag_or(args, name: str, default: bool) -> bool:
    """--flag / --no-flag value when given on the command line, else the setting."""
    value = getattr(args, name, None)
    return bool(default) if value is None else bool(value)


def _looks_like_tl_folder(path: str) -> bool:
    """A tl/ or tl/<language> folder (TL mode), not a game folder."""
    if not os.path.isdir(path):
        return False
    parts = [p.lower() for p in os.path.normpath(path).split(os.sep)]
    if parts[-1] == "tl":
        return True
    return len(parts) >= 2 and parts[-2] == "tl"


def _apply_ai_overrides(config: ConfigManager, engine_id: str, args) -> None:
    """--api-key / --model / --base-url, plus the usual *_API_KEY variables."""
    ts, keys = config.translation_settings, config.api_keys
    api_key = getattr(args, 'api_key', None)
    model = getattr(args, 'model', None)
    base_url = getattr(args, 'base_url', None)

    if engine_id == "gemini":
        keys.gemini_api_key = api_key or keys.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        if model:
            ts.gemini_model = model
    elif engine_id in ("openai", "deepseek"):
        env_name = "DEEPSEEK_API_KEY" if engine_id == "deepseek" else "OPENAI_API_KEY"
        keys.openai_api_key = api_key or keys.openai_api_key or os.environ.get(env_name, "")
        if model:
            ts.openai_model = model
        if base_url:
            ts.openai_base_url = base_url
    elif engine_id == "local_llm":
        if model:
            ts.local_llm_model = model
        if base_url:
            # An explicit URL means "talk to my server", not the built-in runner.
            ts.local_llm_url = base_url
            ts.local_llm_mode = "external"


# ============================================================
# Interactive Mode
# ============================================================

def select_engine() -> str:
    options, icons = [], []
    for code, name, icon, desc in ENGINES:
        if RICH_AVAILABLE:
            options.append(f"{name}  [{BRAND_DIM}]{desc}[/]")
        else:
            options.append(f"{name} — {desc}")
        icons.append(icon)
    choice = print_menu("Select Translation Engine", options, show_back=True, icons=icons)
    if choice == 0: return ""
    return ENGINES[choice - 1][0]


def select_language(title: str = "Select Target Language") -> str:
    options, icons = [], []
    for code, name, icon in LANGUAGES:
        options.append(f"{name} ({code})")
        icons.append(icon)
    options.append("Other (enter manually)")
    icons.append("⌨")
    choice = print_menu(title, options, show_back=True, icons=icons)
    if choice == 0: return ""
    if choice <= len(LANGUAGES): return LANGUAGES[choice - 1][0]
    return get_user_input("Language code", "tr")


def select_source_language() -> str:
    """Source language selection with auto-detect as default."""
    options = ["Auto-detect (recommended)"]
    icons = ["🤖"]
    for code, name, icon in LANGUAGES:
        options.append(f"{name} ({code})")
        icons.append(icon)
    options.append("Other (enter manually)")
    icons.append("⌨")
    choice = print_menu("Select Source Language", options, show_back=True, icons=icons)
    if choice == 0: return ""
    if choice == 1: return "auto"
    if choice - 2 < len(LANGUAGES): return LANGUAGES[choice - 2][0]
    return get_user_input("Source language code", "auto")


def interactive_mode() -> dict:
    """Run interactive setup wizard with Rich UI."""
    config = {'input_path': '', 'target_lang': 'tr', 'source_lang': 'auto',
              'engine': 'google', 'verbose': False, 'deep_scan': False}

    clear_screen()
    print_banner()

    while True:
        choice = print_menu("MAIN MENU", [
            "Full Translation (Game EXE/Project)",
            "Translate Existing TL Folder",
            "Settings", "Help", "Exit"
        ], show_back=False, icons=["🎮", "📁", "⚙", "❓", "👋"])

        if choice == 1:
            print_section_header("STEP 1 — File/Folder Selection", "📂")
            path = get_user_input("Path")
            if not path: print_warning("Path cannot be empty"); continue
            if not os.path.exists(path): print_error(f"File/folder not found: {path}"); continue
            config['input_path'] = os.path.abspath(path)
            config['tl'] = False

            print_section_header("STEP 2 — Target Language", "🌍")
            lang = select_language("Select Target Language")
            if not lang: continue
            config['target_lang'] = lang

            print_section_header("STEP 2b — Source Language", "🌐")
            src = select_source_language()
            if src:
                config['source_lang'] = src
            else:
                continue

            print_section_header("STEP 3 — Translation Engine", "⚡")
            engine = select_engine()
            if not engine: continue
            config['engine'] = engine

            clear_screen(); print_banner()
            build_summary_panel({
                "Path": config['input_path'], "Target": config['target_lang'],
                "Source": config['source_lang'], "Engine": config['engine'],
                "Deep scan": "On" if config['deep_scan'] else "Off",
            }, title="📋 Translation Summary")

            confirm = get_user_input("Start translation? (y/n)", "y")
            if confirm.lower() in ('y', 'yes'): return config

        elif choice == 2:
            print_section_header("TRANSLATE EXISTING TL FOLDER", "📁")
            path = get_user_input("TL Folder Path")
            if not path: print_warning("Path cannot be empty"); continue
            if not os.path.exists(path): print_error(f"Folder not found: {path}"); continue
            config['input_path'] = os.path.abspath(path)
            config['tl'] = True  # this menu entry never actually enabled TL mode

            lang = select_language("Select Target Language")
            if not lang: continue
            config['target_lang'] = lang

            src = select_source_language()
            if src:
                config['source_lang'] = src
            else:
                continue

            engine = select_engine()
            if not engine: continue
            config['engine'] = engine

            clear_screen(); print_banner()
            build_summary_panel({
                "TL Folder": config['input_path'], "Target": config['target_lang'],
                "Source": config['source_lang'], "Engine": config['engine'],
            }, title="📋 Translation Summary")

            confirm = get_user_input("Start translation? (y/n)", "y")
            if confirm.lower() in ('y', 'yes'): return config

        elif choice == 3:
            while True:
                opts = [
                    f"Source Language  [{BRAND_SECONDARY}]{config['source_lang']}[/]" if RICH_AVAILABLE else f"Source: {config['source_lang']}",
                    f"Translation Engine  [{BRAND_SECONDARY}]{config['engine']}[/]" if RICH_AVAILABLE else f"Engine: {config['engine']}",
                    f"Deep scan  [{BRAND_SUCCESS if config['deep_scan'] else BRAND_ERROR}]{'On' if config['deep_scan'] else 'Off'}[/]" if RICH_AVAILABLE else f"Deep scan: {'On' if config['deep_scan'] else 'Off'}",
                    f"Verbose Logging  {f'[{BRAND_SUCCESS}]On[/]' if config['verbose'] else f'[{BRAND_ERROR}]Off[/]'}" if RICH_AVAILABLE else f"Verbose: {'On' if config['verbose'] else 'Off'}",
                ]
                c = print_menu("⚙  SETTINGS", opts, icons=["🌐", "⚡", "🔍", "📝"])
                if c == 0: break
                elif c == 1: config['source_lang'] = get_user_input("Source language code", config['source_lang'])
                elif c == 2: engine = select_engine(); config['engine'] = engine if engine else config['engine']
                elif c == 3: config['deep_scan'] = not config['deep_scan']; print_info(f"Deep scan {'enabled' if config['deep_scan'] else 'disabled'}")
                elif c == 4: config['verbose'] = not config['verbose']; print_info(f"Verbose {'enabled' if config['verbose'] else 'disabled'}")

        elif choice == 4:
            clear_screen(); print_banner()
            if RICH_AVAILABLE:
                help_text = (
                    f"[bold {BRAND_PRIMARY}]RenLocalizer[/] automatically translates Ren'Py visual novels.\n\n"
                    f"[bold {BRAND_ACCENT}]ENGINES[/]\n"
                    f"  [bold]Google Translate[/] — Fast, free, 13 mirrors\n"
                    f"  [bold]OpenAI / DeepSeek[/] — API key required, best quality\n"
                    f"  [bold]Local LLM[/] — Ollama / LM Studio, fully offline\n"
                    f"  [bold]LibreTranslate / Custom[/] — Self-hosted translation servers\n\n"
                    f"[bold {BRAND_ACCENT}]COMMAND LINE[/]\n"
                    f"  [dim]$[/] RenLocalizerCLI translate \"C:\\Games\\MyVN\" -t ru\n"
                    f"  [dim]$[/] RenLocalizerCLI translate \"C:\\Games\\MyVN\" -e deepseek --api-key sk-...\n"
                    f"  [dim]$[/] RenLocalizerCLI translate \"C:\\Games\\MyVN\\game\\tl\\russian\" -t ru   [dim](existing tl/ folder)[/]\n"
                    f"  [dim]$[/] RenLocalizerCLI translate GAME --no-extract-rpa --no-rpyc\n"
                    f"  [dim]$[/] RenLocalizerCLI --help\n"
                )
                console.print(Panel(help_text, title=f"[bold {BRAND_PRIMARY}]❓ Help[/]", border_style=BRAND_DIM, padding=(1, 2)))
            else:
                print("""
  HELP ───────────────────────────────────
  RenLocalizer CLI translates Ren'Py games.
  
  ENGINES: Google, Bing, OpenAI, DeepSeek, Gemini, Local LLM, LibreTranslate, Custom

  USAGE:
    RenLocalizerCLI translate <game folder> -t ru
    RenLocalizerCLI translate <game folder> -e deepseek --api-key sk-...
    RenLocalizerCLI translate <game>/game/tl/russian -t ru   (existing tl/ folder)
    RenLocalizerCLI --help
  ─────────────────────────────────────────""")
            console.input(f"\n  [{BRAND_DIM}]Press Enter to continue...[/]" if RICH_AVAILABLE else "\n  Press Enter...")

        elif choice == 5:
            if RICH_AVAILABLE: console.print(f"\n  [{BRAND_DIM}]Goodbye! 👋[/]\n")
            else: print("\n  Goodbye!\n")
            sys.exit(0)

    return config


# ============================================================
# Main Entry Point
# ============================================================

def _add_translate_options(p: argparse.ArgumentParser, suppress: bool) -> None:
    """Translation options shared by the top-level parser and 'translate'."""
    def d(value):
        return argparse.SUPPRESS if suppress else value

    p.add_argument("--config", default=d(None), help="JSON file overriding settings (same sections as config.json)")
    p.add_argument("--target-lang", "-t", default=d("tr"), help="Target language: code or name, e.g. tr, ru, spanish (default: tr)")
    p.add_argument("--source-lang", "-s", default=d("auto"), help="Source language code (default: auto)")
    p.add_argument("--engine", "-e", default=d("google"), choices=[e[0] for e in ENGINES], help="Translation engine (default: google)")
    p.add_argument("--api-key", default=d(None), help="API key for openai/deepseek/gemini (or OPENAI_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY)")
    p.add_argument("--model", default=d(None), help="Model name for AI engines")
    p.add_argument("--base-url", default=d(None), help="OpenAI-compatible endpoint (OpenRouter, LM Studio, Ollama...)")
    p.add_argument("--lt-url", default=d(""), help="LibreTranslate/Custom endpoint URL")
    p.add_argument("--lt-key", default=d(""), help="LibreTranslate/Custom API key")
    p.add_argument("--tl", action="store_true", default=d(False),
                   help="Translate an existing game/tl/<lang> folder in place (auto-detected for tl paths)")
    p.add_argument("--extract-rpa", action=argparse.BooleanOptionalAction, default=d(None),
                   help="Extract .rpa archives first (default: the app setting, normally on)")
    p.add_argument("--rpyc", action=argparse.BooleanOptionalAction, default=d(None),
                   help="Read compiled .rpyc scripts (default: the app setting)")
    p.add_argument("--language-init", action=argparse.BooleanOptionalAction, default=d(None),
                   help="Write game/zzz_<lang>_language.rpy so the game starts translated (default: the app setting, normally on)")
    p.add_argument("--deep-scan", "-d", action="store_true", default=d(False), help="Enable deep scanning")
    p.add_argument("--verbose", "-v", action="store_true", default=d(False), help="Enable verbose logging")
    p.add_argument("--interactive", "-i", action="store_true", default=d(False), help="Run in interactive menu mode")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"RenLocalizer CLI v{VERSION} — Ren'Py Game Translation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # TRANSLATE — options are accepted before or after the command. The
    # subparser uses SUPPRESS defaults so it never overwrites values given
    # before "translate" ("-e local_llm translate GAME" used to run Google).
    t = subparsers.add_parser('translate', help='Translate a game or project')
    t.add_argument("input_path", nargs='?', default=None, help="Path to game executable, project directory, or TL folder")
    _add_translate_options(t, suppress=True)

    # ACTIVATE-LANGUAGE
    a = subparsers.add_parser(
        'activate-language',
        help="Make the game start in a translated language (Ren'Py does not list tl/ folders by itself)",
    )
    a.add_argument("input_path", help="Game folder, game/ folder or game executable")
    a.add_argument("--lang", "-t", default=None,
                   help="Language folder under game/tl (default: the only one, or list them)")
    a.add_argument("--remove", action="store_true", help="Remove the activation file instead")

    # PSEUDO
    p = subparsers.add_parser('pseudo', help='Generate pseudo-localized text for UI testing')
    p.add_argument("input_path", help="Path to game directory or tl folder")
    p.add_argument("--mode", choices=["expand", "accent", "both"], default="both", help="Pseudo mode")
    p.add_argument("--output", "-o", help="Output directory")

    # Legacy direct mode
    parser.add_argument("legacy_input_path", nargs='?', default=None, metavar='input_path',
                        help="Path to game executable, project directory, or translation file")
    _add_translate_options(parser, suppress=False)
    parser.add_argument("--version", action="version", version=f"RenLocalizer CLI v{VERSION}")

    argv = sys.argv[1:]
    # "RenLocalizerCLI <game> -t ru" (no command): argparse would read <game>
    # as the command name and fail, so the documented short form never worked.
    if (argv and not any(a in ("translate", "pseudo", "activate-language") for a in argv)
            and any(not a.startswith("-") for a in argv)
            and not any(a in ("-h", "--help", "--version") for a in argv)):
        argv = ["translate"] + argv
    args = parser.parse_args(argv)

    # Normalize legacy mode
    if args.command is None and hasattr(args, 'legacy_input_path') and args.legacy_input_path:
        args.input_path = args.legacy_input_path

    # Interactive mode
    if getattr(args, 'interactive', False) or (args.command is None and not args.legacy_input_path):
        config = interactive_mode()
        if config['input_path']:
            from types import SimpleNamespace
            ns = SimpleNamespace(
                input_path=config['input_path'], target_lang=config['target_lang'],
                source_lang=config['source_lang'], engine=config['engine'],
                verbose=config.get('verbose', False), deep_scan=config.get('deep_scan', False),
                config=None, lt_url='', lt_key='', command='translate',
                tl=config.get('tl', False), extract_rpa=None, rpyc=None, language_init=None,
                api_key=None, model=None, base_url=None,
            )
            return run_translate_command(ns)
        return 0

    # Subcommands
    if args.command == 'translate' or args.command is None:
        return run_translate_command(args)

    if args.command == 'pseudo':
        return run_pseudo_command(args)

    if args.command == 'activate-language':
        return run_activate_language_command(args)

    return 0


# ============================================================
# Activate-Language Command
# ============================================================

def _resolve_game_dir(path: str) -> Optional[str]:
    """game/ folder for a project root, game/ itself, a tl/ path, the exe or a macOS app."""
    from src.utils.path_manager import unwrap_mac_app
    path = unwrap_mac_app(os.path.abspath(path))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    parts = os.path.normpath(path).split(os.sep)
    lowered = [p.lower() for p in parts]
    if "tl" in lowered:
        idx = len(lowered) - 1 - lowered[::-1].index("tl")
        path = os.sep.join(parts[:idx]) or path
    if os.path.basename(os.path.normpath(path)).lower() == "game" and os.path.isdir(path):
        return path
    candidate = os.path.join(path, "game")
    return candidate if os.path.isdir(candidate) else None


def run_activate_language_command(args) -> int:
    """Write (or remove) game/zzz_<lang>_language.rpy."""
    from src.core.pipeline.saving import (
        create_language_init_file, list_tl_languages, remove_language_init_files,
    )

    game_dir = _resolve_game_dir(args.input_path)
    if not game_dir:
        print_error(f"No game/ folder found for: {args.input_path}")
        return 1

    if args.remove:
        removed = remove_language_init_files(game_dir)
        if removed:
            print_success("Language activation removed; the game starts in its own language again.")
        else:
            print_info("No language activation file was found in game/.")
        return 0

    languages = list_tl_languages(game_dir)
    if not languages:
        print_error("No translation folders found in game/tl. Translate the game first.")
        return 1

    config = ConfigManager()
    wanted = (args.lang or "").strip()
    if wanted:
        wanted = config.normalize_renpy_language_code(wanted)
        match = next((l for l in languages if l.lower() == wanted.lower()), None)
        if not match:
            print_error(f"game/tl/{wanted} does not exist. Available: {', '.join(languages)}")
            return 1
        language = match
    elif len(languages) == 1:
        language = languages[0]
    else:
        print_error(f"Several translations found, pick one with --lang: {', '.join(languages)}")
        return 1

    messages = []
    create_language_init_file(game_dir, language, config, lambda level, msg: messages.append(msg), force=True)
    if not (Path(game_dir) / f"zzz_{language}_language.rpy").exists():
        print_error("Could not write the language activation file. " + " ".join(messages))
        return 1
    print_success(f"The game will now start in: {language}")
    return 0


# ============================================================
# Pseudo Command
# ============================================================

def run_pseudo_command(args) -> int:
    """Generate pseudo-localized translations for UI testing."""
    print_banner()
    print_section_header("PSEUDO-LOCALIZATION", "🧪")

    input_path = os.path.abspath(args.input_path)
    if not os.path.exists(input_path):
        print_error(f"Path not found: {input_path}")
        return 1

    print_key_value("Input", input_path, "📁")
    print_key_value("Mode", args.mode, "⚙")
    output_dir = args.output or os.path.join(input_path, "game", "tl", "pseudo") if os.path.isdir(input_path) else os.path.join(os.path.dirname(input_path), "pseudo")
    print_key_value("Output", output_dir, "📂")
    console.print()

    translator = PseudoTranslator(mode=args.mode)
    rpy_files = []
    if os.path.isfile(input_path) and input_path.lower().endswith('.rpy'):
        rpy_files = [input_path]
    else:
        game_dir = os.path.join(input_path, 'game') if os.path.isdir(os.path.join(input_path, 'game')) else input_path
        for root, dirs, files in os.walk(game_dir):
            if '/tl/' in root.replace('\\', '/') or '\\tl\\' in root:
                continue
            for f in files:
                if f.lower().endswith('.rpy'):
                    rpy_files.append(os.path.join(root, f))

    if not rpy_files:
        print_warning("No .rpy files found.")
        return 1

    print_info(f"Processing {len(rpy_files)} files...")
    console.print()

    import re
    pattern = re.compile(r'^(\s*)(\w+)?\s*"([^"]+)"', re.MULTILINE)
    translated_count = 0
    os.makedirs(output_dir, exist_ok=True)

    if RICH_AVAILABLE:
        with Progress(SpinnerColumn("dots", style=BRAND_PRIMARY),
                      TextColumn("[bold]{task.description}[/]"),
                      BarColumn(bar_width=30, style=BRAND_DIM, complete_style=BRAND_PRIMARY, finished_style=BRAND_SUCCESS),
                      MofNCompleteColumn(), console=console) as progress:
            task = progress.add_task("Processing", total=len(rpy_files))
            for rpy_file in rpy_files:
                rel = os.path.relpath(rpy_file, input_path)
                out = os.path.join(output_dir, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                try:
                    with open(rpy_file, 'r', encoding='utf-8') as f: content = f.read()
                    def replace(m):
                        nonlocal translated_count; translated_count += 1
                        return f'{m.group(1)}{m.group(2) or ""} "{translator._apply_pseudo(m.group(3))}"'
                    with open(out, 'w', encoding='utf-8') as f: f.write(pattern.sub(replace, content))
                except Exception as e: print_error(f"{rel}: {e}")
                progress.advance(task)
    else:
        for rpy_file in rpy_files:
            rel = os.path.relpath(rpy_file, input_path)
            out = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                with open(rpy_file, 'r', encoding='utf-8') as f: content = f.read()
                def replace(m):
                    nonlocal translated_count; translated_count += 1
                    return f'{m.group(1)}{m.group(2) or ""} "{translator._apply_pseudo(m.group(3))}"'
                with open(out, 'w', encoding='utf-8') as f: f.write(pattern.sub(replace, content))
            except Exception as e: print_error(f"{rel}: {e}")

    console.print()
    print_success(f"Pseudo-localized {translated_count} strings")
    print_key_value("Output", output_dir, "📂")
    return 0


if __name__ == "__main__":
    sys.exit(main())
