# ❓ Frequently Asked Questions (FAQ)

Everything you need to know about translating Ren'Py visual novels with RenLocalizer.

---

## 🚀 General & Gameplay

### ❔ Does RenLocalizer modify my original game files?
**No, never.** All translation data is isolated within the `tl/<language>/` directory inside the game folder. Your original game scripts (`.rpy`, `.rpyc`) remain 100% untouched. To completely uninstall a translation, simply delete the `tl/<language>/` folder.

### ❔ How do I activate the translation in-game?
1. Launch the game normally.
2. Open the in-game **Preferences / Settings** screen.
3. Find the **Language** setting and select your translated language.
4. All dialogues, menus, and interfaces will immediately switch to your language!

### ❔ Can I stop and resume translation?
**Yes!** Click **"STOP"** (⏹) at any time. Everything translated up to that point is preserved in the local Translation Memory (`.cache/tm/`). When you resume later, previously translated lines are skipped instantly.

---

## 🤖 AI Engines & Translation Modes

### ❔ What is the difference between Scene, JSON, and XML modes?
- 🎭 **Scene / Screenplay Mode (Recommended):** Sends dialogues formatted like a theatre script with speaker names. The AI understands character dynamics, who is being spoken to, gender agreement, and tone. Best for visual novels.
- 📦 **Standard Structured Mode (JSON):** Sends lines in strict `{ "id": "text" }` pairs. Prevents any line desynchronization. Perfect for UI menus, items, and settings.
- 📄 **Legacy Grouping Mode (XML):** Packages text in `<item id="N">...</item>` tags. Best for smaller or older local models (e.g. 3B/7B) that may struggle with strict JSON formatting.

### ❔ How does Tencent Hy-MT2 work?
Tencent Hy-MT2 is a specialized translation model family. When selected in Local LLM:
- Automatically applies official instruction templates (no system prompt).
- Activates the official model-card sampling recipe (`temperature: 0.7`, `top_p: 0.6`, `top_k: 20`, `repetition_penalty: 1.05`).
- Runs at lightning speed even on budget GPUs (e.g. RTX 3050 4GB).

### ❔ Why did my AI model refuse to translate adult content?
Standard commercial models (ChatGPT, vanilla Llama) have strict moral safety guardrails that block NSFW / 18+ content.  
**Solution:** If translating adult visual novels, use **Uncensored / Abliterated** models in Ollama or LM Studio (such as `dolphin`, `qwen-uncensored`, or `abliterated` Llama variants).

### ❔ How do I fix `429 Too Many Requests` API errors?
Under **⚡ Advanced AI Tuning**:
1. Lower **AI Concurrency** to `1` or `2`.
2. Increase **AI Timeout** or add a slight delay between requests.

---

## 🛡️ Errors & Troubleshooting

### ❔ Why are some character names or words like `[player]` left in English?
RenLocalizer features **SyntaxGuard**, which intentionally shields code constructs:
- Variables like `[player]`, `[score]`, or `{b}` tags must never be translated into dictionary words, or Ren'Py will crash with a variable lookup error.
- Technical parameters (image paths, sound files, hex color codes) are automatically filtered out.

### ❔ How do I protect specific character names from being translated?
Edit the `glossary.json` file in your RenLocalizer directory:
```json
{
  "Blackwood": "Blackwood",
  "Silverstone": "Silverstone"
}
```
Any term defined in the glossary will remain strictly preserved or replaced according to your rule.

### ❔ How does RenLocalizer prevent "Duplicate translation" crashes?
Ren'Py 7.5+ and 8.x crash if the same `old "..."` line is defined twice in `translate strings:` blocks. RenLocalizer automatically deduplicates all strings across multiple scripts before saving, guaranteeing zero duplicate string crashes.

### ❔ Turkish / Cyrillic / Non-Latin characters appear as square boxes (`□□□`)
This means the original game font does not include Unicode glyphs for your language. 
- In **Standard Mode**, the runtime hook automatically applies Unicode font fallback.
- In **Native TLID Mode**, ensure the game's font is set to a Unicode font (e.g. Noto Sans or DejaVu Sans) in the game settings or options.rpy.

### ❔ How can I make Google Translate faster?
- Keep **Concurrent Threads** at `6–8`.
- Set **Request Delay** to `0.3s–0.5s`.
- Keep **Aggressive Retry** turned `OFF`.

### ❔ "Could not initialize GLX" on Linux
Run with software rendering fallback:
```bash
QT_QUICK_BACKEND=software ./RenLocalizer.sh
```

---

## ℹ️ General & Support

### ❔ Is RenLocalizer portable?
**Yes!** Preferences are saved in `config.json` next to the executable. You can copy the folder to a USB stick and run it on any computer.

### ❔ How do I report a bug or request a feature?
Open an issue on GitHub:  
👉 [https://github.com/Lord0fTurk/RenLocalizer/issues](https://github.com/Lord0fTurk/RenLocalizer/issues)

Please include your OS, RenLocalizer version, and the log output from the app.

### ❔ How do I support development?
- ⭐ Star the project on GitHub
- 💬 Share it in visual novel communities
- 💖 Support on Patreon: [https://www.patreon.com/cw/LordOfTurk](https://www.patreon.com/cw/LordOfTurk)
