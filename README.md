<div align="center">

<img src="https://img.shields.io/badge/status-in%20development-orange?style=for-the-badge" alt="Status: In Development"/>
<img src="https://img.shields.io/badge/python-%3E%3D3.11-brightgreen?style=for-the-badge" alt="Python"/>
<img src="https://img.shields.io/badge/managed%20with-uv-blueviolet?style=for-the-badge" alt="uv"/>
<img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License"/>

# 🤖 DeepSeek Browser Agent (Python port)

**An autonomous AI coding agent that runs entirely for free — no API key required.**

It drives a real browser to talk to [DeepSeek](https://chat.deepseek.com), giving you a Claude Code / Cursor-style coding agent powered by DeepSeek's models at zero cost.

This is a Python port (using [Playwright for Python](https://playwright.dev/python/) and
[uv](https://docs.astral.sh/uv/)) of the original Node.js
[deepseek-browser-agent](https://github.com/Windows-Feilulu/deepseek-browser-agent).

</div>

---

## 🧠 How It Works

Most AI coding agents talk to a paid API. This one doesn't.

Instead, it uses **Playwright** to control a real Chromium browser, navigates to `chat.deepseek.com`,
sends your task, waits for the response, and parses it to extract tool calls — all automatically.
Your local files and terminal are wired up as tools the AI can use, so it can read code, write files,
run commands, and build complete projects step by step.

```
Your Terminal
     │
     ▼
 Agent Core          ← orchestrates the loop
     │
     ├──► Browser (Playwright)  ← talks to chat.deepseek.com
     │         │
     │    DeepSeek AI  ← thinks, decides what tool to use
     │         │
     └──► Tool Executor  ← reads/writes files, runs commands
              │
         Your Project
```

---

## 📦 Installation

This project uses [uv](https://docs.astral.sh/uv/) to manage a virtual environment and dependencies.

```bash
# 1. Sync the virtual environment (creates .venv and installs dependencies)
uv sync

# 2. Download the Playwright Chromium browser (one time, ~150 MB)
uv run playwright install chromium
```

**Requirements:** Python ≥ 3.11

---

## 🚀 Quick Start

**1. First run — log in to DeepSeek:**
```bash
uv run deepseek-agent --interactive
```
A browser window opens. Log in to your DeepSeek account, then come back to the terminal and press **Enter**.
Your session is saved — you only do this once.

**2. Give it a task:**
```bash
uv run deepseek-agent "build a REST API in FastAPI with user authentication"
```

**3. Use the short alias `dsa` from any project folder:**
```bash
cd ~/my-project
uv run --project /path/to/deepseek-agent dsa "add input validation to all my API routes"
```

> Tip: run `uv tool install --editable .` from this project directory to put `deepseek-agent`
> and `dsa` on your `PATH` so you don't need `uv run` every time.

### Running without a visible window (virtual display)

By default the agent opens a real, visible Chromium window (this is intentional — DeepSeek can
flag plain `--headless` browsers as bots). If you don't want a window popping up on your screen,
run it inside an Xvfb virtual display instead of using `--headless`:

```bash
uv run deepseek-agent -v --interactive
# or: ./start.sh -v -i
```

This requires Xvfb to be installed on your system (e.g. `sudo apt install xvfb`). You can also
set it permanently via `"VIRTUAL_DISPLAY": true` in `deepseek-agent.config.json`.

---

## 💻 Usage

```
deepseek-agent [OPTIONS] [TASK]

  -t, --task <task>        Task to run (or just type it as the last argument)
  -f, --task-file <file>   Read task from file (overrides -t)
  -i, --interactive        Keep browser open, run multiple tasks in a session
  -d, --dir <path>         Set working directory (default: current directory)
  --debug                  Print raw AI responses to the terminal
  --headless               Run browser invisibly (requires prior login)
  --save-log                Save full session log to ~/.deepseek-agent/logs/
  --calibrate               Auto-detect DOM selectors (run if agent breaks)
  -v, --virtual-display     Run non-headless inside an Xvfb virtual display
                             (no real window, avoids headless bot detection)
  -h, --help                Show help

Aliases:
  dsa                       Short form of deepseek-agent
```

### Examples

```bash
# Single task — runs and exits
uv run deepseek-agent "create a Python script that scrapes Hacker News"

# Interactive mode — keeps browser open between tasks
uv run deepseek-agent --interactive

# Run on a specific project
uv run dsa --dir ~/projects/my-app "refactor all callbacks to async/await"

# Debug mode (shows what DeepSeek is actually outputting)
uv run dsa --debug "build a calculator"

# Headless mode (faster — browser runs in background)
uv run dsa --headless "write unit tests for utils.py"

# In interactive mode, type 'new' to start a fresh chat:
❯ Task: new
```

---

## ⚙️ Configuration

### Global config — applies everywhere

Create `~/.deepseek-agent/config.json`:

```json
{
  "HEADLESS": true,
  "MAX_ITERATIONS": 50,
  "STABLE_DELAY": 3000,
  "DEBUG": false
}
```

### Per-project config — overrides global

Drop `deepseek-agent.config.json` in your project root:

```json
{
  "MAX_ITERATIONS": 60,
  "MAX_OUTPUT_LENGTH": 12000
}
```

### All settings

| Setting | Default | Description |
|---|---|---|
| `HEADLESS` | `false` | Hide the browser window |
| `MAX_ITERATIONS` | `60` | Max agent steps per task before stopping |
| `RESPONSE_TIMEOUT` | `180000` | Max ms to wait for a response (3 min) |
| `STABLE_DELAY` | `2500` | Ms of silence that means DeepSeek is done |
| `SEND_DELAY` | `400` | Ms between typing and pressing Enter |
| `MAX_OUTPUT_LENGTH` | `8000` | Truncate long command outputs sent to AI |
| `DEBUG` | `false` | Print raw AI responses to terminal |
| `SESSION_DIR` | `~/.deepseek-agent/session` | Where browser cookies are saved |
| `VIRTUAL_DISPLAY` | `false` | Run the non-headless browser inside an Xvfb virtual display instead of a real window |

---

## 🛠️ Available Tools

The agent can use these tools autonomously to complete your task:

| Tool | Description |
|---|---|
| `read_file` | Read a file's contents, optionally by line range |
| `write_file` | Create or overwrite a file (auto-creates directories) |
| `append_to_file` | Append text to an existing file |
| `replace_in_file` | Find and replace text in a file (regex supported) |
| `delete_file` | Permanently delete a file |
| `list_directory` | List directory contents, optionally recursive |
| `create_directory` | Create a directory and all parents |
| `move_file` | Move or rename a file or directory |
| `copy_file` | Copy a file to a new location |
| `get_file_info` | Get file metadata (size, line count, dates) |
| `run_command` | Execute any shell command |
| `find_files` | Find files by name pattern (e.g. `*.ts`) |
| `search_in_files` | Search text inside files (like `grep -r`) |
| `ask_user` | Ask the user a clarifying question and wait for a reply |
| `read_url` | Fetch and read the content of a URL |
| `write_files` | Write multiple files at once (batch scaffold) |

---

## 📂 Where Data is Stored

Everything lives in `~/.deepseek-agent/` in your home directory:

```
~/.deepseek-agent/
├── session/        ← Browser cookies (login once, runs forever)
├── logs/           ← Session logs (only saved with --save-log)
└── config.json     ← Your global settings
```

File-modifying tools also write a backup of the original file (plus a
`backup_manifest.json`) under `./backups/<session-id>/` in your working directory
before changing anything.

---

## 🔧 Troubleshooting

### Agent responds but creates no files
The browser DOM rendered the AI's response in a way the parser didn't catch. Run with `--debug` to see exactly what's being received:
```bash
uv run deepseek-agent --debug "build a calculator"
```

### Agent stops responding / loops
DeepSeek's UI may have changed. Run the calibration tool — it inspects the live DOM and prints updated selectors:
```bash
uv run deepseek-agent --calibrate
# or the deeper standalone report:
uv run deepseek-agent-calibrate
```

### Login session expired
Just run without `--headless` — the browser opens and you log in again:
```bash
uv run deepseek-agent --interactive
```

### Chromium didn't download automatically
```bash
uv run playwright install chromium
```

### Response times out on long tasks
Increase the timeout in your config:
```json
{ "RESPONSE_TIMEOUT": 300000, "STABLE_DELAY": 4000 }
```

---

## 🗂️ Project Structure

```
deepseek-agent/
├── src/deepseek_agent/
│   ├── cli.py            ← CLI entry point and argument parsing
│   ├── agent.py           ← Core agent loop (send → wait → parse → execute)
│   ├── browser.py          ← Playwright controller for chat.deepseek.com
│   ├── tools.py             ← All 16 filesystem, shell, and web tools
│   ├── parser.py             ← Extracts tool calls from AI responses (7 strategies)
│   ├── prompt.py               ← System prompt and conversation history manager
│   ├── config.py                ← Configuration loader (global + per-project)
│   ├── logger.py                 ← ANSI-colored terminal output
│   ├── backup.py                  ← Pre-modification file backups
│   └── calibrate.py                ← DOM selector inspector / auto-fix tool
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## ⚠️ Disclaimer

This project automates a web browser to interact with chat.deepseek.com. Automating web UIs may
violate the terms of service of the website being automated. Use this tool for **personal and
development purposes only**. The authors take no responsibility for account suspensions or other
consequences of use.

---

## 📄 License

MIT — see [LICENSE](./LICENSE) for details.

---

<div align="center">

**Built with Playwright (Python) · Managed with uv · Powered by DeepSeek**

Ported from the original Node.js project by Omar Azam /
[Windows-Feilulu/deepseek-browser-agent](https://github.com/Windows-Feilulu/deepseek-browser-agent).

</div>
