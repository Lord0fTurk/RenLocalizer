# ⚙️ Settings & Translation Engines

RenLocalizer organizes all configuration options into clean, themed cards on the main dashboard. Here is a complete breakdown of every option, engine, and AI tuning parameter.

---

## 🎨 Interface & System Settings

| Setting | Options | Description |
|:---|:---|:---|
| 🌐 **UI Language** | EN, TR, DE, ES, FR, RU, FA, ZH-CN, JA | Changes the application language dynamically. |
| 🎨 **Theme** | Dark, Light, Red, Turquoise, Green, Neon | Select the visual color palette that suits your style. |
| 🔄 **Auto Update** | Check on startup | Checks GitHub Releases for new updates automatically. |

---

## 🤖 Translation Engines Overview

RenLocalizer supports 7 distinct translation backends:

### 1. 🌐 Google Translate (Free & Instant — Default)
- **API Key:** Not required (100% Free).
- **How it works:** Uses 13 rotating Google mirror endpoints and Lingva fallback.
- **Best for:** Fast, zero-configuration translation for any game.

### 2. 🧠 OpenAI (GPT-4o / GPT-4o-mini)
- **API Key:** Your OpenAI API Key (`sk-...`).
- **Models:** `gpt-4o-mini` (fast and economical) or `gpt-4o` (maximum literary quality).
- **Base URL:** Optional; leave blank or point to OpenRouter or compatible proxies.

### 3. ⚡ DeepSeek (V3 / R1)
- **API Key:** Your DeepSeek API Key.
- **Model:** `deepseek-chat` or `deepseek-reasoner`.
- **Base URL:** Auto-set to `https://api.deepseek.com/v1`.
- **Best for:** Incredibly high translation quality at a fraction of standard API costs.

### 4. 💎 Google Gemini
- **API Key:** Your Google AI Studio API Key (`AIza...`).
- **Model:** `gemini-2.0-flash`, `gemini-1.5-flash`, etc.
- **Best for:** High-speed API translation with massive token context windows.

### 5. 🏠 Local LLM (Ollama / LM Studio)
- **Server URL:** `http://localhost:11434/v1` (Ollama) or `http://localhost:1234/v1` (LM Studio).
- **Model Name:** Any local model (e.g. `qwen2.5-coder:7b`, `llama3.1:8b`).
- **Best for:** 100% offline, private translation.
- 🔞 **Adult Games:** Use uncensored models (e.g. `dolphin`, `abliterated`) to prevent moral refusal on NSFW content.

### 6. 🎯 Tencent Hy-MT2 (Specialized Translation Profile)
- **Mode:** Auto-detect, Force Hy-MT2, or Generic.
- **Features:** When using Tencent Hy-MT models (e.g. `tencent/Hy-MT2-1.8B-GGUF`), activates the official model-card sampling recipe (`temp: 0.7`, `top_p: 0.6`, `top_k: 20`, `rep_pen: 1.05`) and instruction templates without system prompts.
- **Best for:** High-speed, lightweight local translation on budget GPUs (e.g. RTX 3050 4GB).

### 7. 🐳 LibreTranslate & Custom Endpoints
- Connect to self-hosted LibreTranslate Docker containers or custom translation servers.

---

## 🎭 AI Translation Modes & Batching

When using AI engines, you can choose how texts are structured before being sent to the model:

| Mode | Format | When to use |
|:---|:---|:---|
| 🎭 **Scene / Screenplay Mode** | Theatre script flow (`[0] Alice: Text`) | **Recommended for visual novels.** Maintains character voices, gender agreement, and narrative context. |
| 📦 **JSON Document Mode** | Structured `{ "id": "text" }` | Guarantees strict data integrity and zero line desync. Ideal for menus and system UI strings. |
| 📄 **XML Tag Mode** | Tag wrapping `<item id="N">text</item>` | Highly resilient for smaller or older models (e.g. 3B/7B) that struggle with JSON syntax. |

### 📏 Scene Block Size (`aiSceneBatchSize`)
- Available when **Scene Mode** is active (slider range: **5 to 50 lines**).
- Controls how many dialogue lines are grouped into a single scene context. Default is **15–20 lines**.

---

## ⚡ Advanced AI Tuning Parameters

Fine-tune model behavior under the **⚡ Advanced AI Tuning** card:

| Parameter | Default | Range | What it does |
|:---|:---:|:---:|:---|
| **AI Temperature** | `0.30` | 0.0 – 1.0 | Lower = more consistent and literal; Higher = more creative. |
| **Max Tokens** | `4096` | 256 – 8192 | Maximum output tokens per request. |
| **AI Timeout** | `60s` | 10s – 300s | Maximum wait time for a model response before retrying. |
| **AI Batch Size** | `50` | 1 – 50 | Number of lines sent per request chunk in JSON/XML mode. |
| **AI Concurrency** | `2` | 1 – 10 | Number of simultaneous parallel requests. |
| **Custom System Prompt** | *(Empty)* | Text | Override default prompts with your own custom translator instructions. |

---

## 📦 Output Modes & Memory

- **Native TLID (Default):** Generates clean, native Ren'Py `translate` blocks and auto-exported `translate strings:`. Pure native speed with zero game scripts.
- **Standard Mode:** Generates `strings.json` and injects `zzz_renlocalizer_runtime.rpy` for dynamic runtime replacement.
- **Translation Memory (TM):** Caches every translated line in `.cache/tm/`. Unchanged lines are never re-translated, saving time, API tokens, and preventing rate limits.
