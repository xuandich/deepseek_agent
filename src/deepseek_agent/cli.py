#!/usr/bin/env python3
"""cli.py — CLI entry point for DeepSeek Agent."""
from __future__ import annotations

import asyncio
import re
import signal
import sys
import traceback
from pathlib import Path

from . import backup, logger
from .agent import DeepSeekAgent
from .config import config

# ─────────────────────────────────────────────
#  Parse CLI arguments
# ─────────────────────────────────────────────


def _parse_args(args: list[str]) -> dict:
    opts = {
        "task": None,
        "task_file": None,
        "interactive": False,
        "debug": False,
        "headless": False,
        "save_log": False,
        "working_dir": None,
        "calibrate": False,
        "help": False,
        "virtual_display": False,
    }

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-i", "--interactive"):
            opts["interactive"] = True
        elif a == "--debug":
            opts["debug"] = True
        elif a == "--headless":
            opts["headless"] = True
        elif a == "--save-log":
            opts["save_log"] = True
        elif a == "--calibrate":
            opts["calibrate"] = True
        elif a in ("-v", "--virtual-display"):
            opts["virtual_display"] = True
        elif a in ("-h", "--help"):
            opts["help"] = True
        elif a in ("-f", "--task-file"):
            i += 1
            opts["task_file"] = args[i] if i < len(args) else None
        elif a in ("-d", "--dir"):
            i += 1
            opts["working_dir"] = args[i] if i < len(args) else None
        elif a in ("-t", "--task"):
            i += 1
            opts["task"] = args[i] if i < len(args) else None
        elif not a.startswith("-"):
            # Treat it (and everything after it) as the inline task
            opts["task"] = " ".join(args[i:])
            i = len(args)
            continue
        i += 1

    return opts


# ─────────────────────────────────────────────
#  Help text
# ─────────────────────────────────────────────


def _print_help() -> None:
    print(f"""
\x1b[1mDEEPSEEK AGENT\x1b[0m — AI Coding Agent via Browser Automation

\x1b[33mUSAGE\x1b[0m
  deepseek-agent [OPTIONS] [TASK]

\x1b[33mOPTIONS\x1b[0m
  -t, --task <task>    Task to run (can also be the last argument without a flag)
  -f, --task-file <file>   Read task from file (overrides -t). Replaces \\r\\n with \\n.
  -i, --interactive    Interactive REPL mode — keep browser open, run multiple tasks
  -d, --dir <path>     Set working directory (default: current directory)
  --debug              Verbose debug output
  --headless           Run browser in headless mode (must be logged in already)
  --save-log           Save conversation log to ~/.deepseek-agent/logs/
  --calibrate          Open browser and print DOM info to help fix selectors
  -v, --virtual-display   Run the managed browser non-headless inside an Xvfb
                           virtual display (no real window, avoids bot detection)
  -h, --help           Show this help

\x1b[33mEXAMPLES\x1b[0m
  # Run a single task
  deepseek-agent "Create a REST API in Express with CRUD for users"

  # Read task from a file
  deepseek-agent -f my_task.txt

  # Combine with working directory
  deepseek-agent -d ~/projects/myapp -f task.md

  # Interactive mode (recommended)
  deepseek-agent --interactive

  # Run on a specific project directory
  deepseek-agent --dir ~/projects/myapp "Add type hints to this project"

  # Debug mode (shows raw responses)
  deepseek-agent --debug "Write a binary search in Python"

  # Headless (faster, requires prior login)
  deepseek-agent --headless "Refactor main.py to use async/await"

\x1b[33mFIRST-TIME SETUP\x1b[0m
  1. uv sync && uv run playwright install chromium
  2. uv run deepseek-agent -i     (opens browser, log in to DeepSeek, then use normally)
     Session is saved — you only log in once.

\x1b[33mCONFIG FILE\x1b[0m
  Create \x1b[36mdeepseek-agent.config.json\x1b[0m in your working directory to override settings:
  {{
    "HEADLESS": true,
    "MAX_ITERATIONS": 50,
    "STABLE_DELAY": 3000
  }}
""")


def _read_task_from_file(file_path: str) -> str:
    resolved = Path(file_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Task file not found: {resolved}")
    content = resolved.read_text(encoding="utf-8")
    content = re.sub(r"\r\n|\n\r", "\n", content)
    if not content.strip():
        raise ValueError(f"Task file is empty: {resolved}")
    return content


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────


async def _async_main() -> int:
    opts = _parse_args(sys.argv[1:])

    if opts["help"]:
        _print_help()
        return 0

    if opts["debug"]:
        config.DEBUG = True
    if opts["headless"]:
        config.HEADLESS = True
    if opts["virtual_display"]:
        config.VIRTUAL_DISPLAY = True
    if opts["working_dir"]:
        resolved = Path(opts["working_dir"]).resolve()
        if not resolved.exists():
            logger.error(f"Working directory not found: {resolved}")
            return 1
        config.WORKING_DIR = str(resolved)

    logger.banner()
    logger.info(f"Working directory : \x1b[36m{config.WORKING_DIR}\x1b[0m")
    logger.info(f"Session directory : \x1b[36m{config.SESSION_DIR}\x1b[0m")
    logger.info(f"Headless mode     : \x1b[36m{config.HEADLESS}\x1b[0m")
    logger.info(f"Debug mode        : \x1b[36m{config.DEBUG}\x1b[0m")
    if config.VIRTUAL_DISPLAY:
        logger.info(f"Virtual display   : \x1b[36m{config.VIRTUAL_DISPLAY}\x1b[0m")
    print("")

    agent = DeepSeekAgent(save_log=opts["save_log"])

    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, main_task.cancel)
        except (NotImplementedError, RuntimeError):
            pass

    exit_code = 0
    try:
        # ── Calibrate mode ─────────────────────────────────────────────────
        if opts["calibrate"]:
            logger.header("Calibration Mode — Reading DOM selectors")
            await agent.init()
            await agent.browser.dump_debug_info()
            await agent.browser.screenshot()
            logger.info("Done. Check the output above to update selectors in browser.py if needed.")
            return 0

        # ── Task file takes priority over an inline task ────────────────────
        final_task = opts["task"]
        if opts["task_file"]:
            if opts["interactive"]:
                logger.warn("--task-file is ignored in interactive mode.\n")
            else:
                try:
                    final_task = _read_task_from_file(opts["task_file"])
                    logger.info(f"Loaded task from file: {opts['task_file']}")
                    if config.DEBUG:
                        logger.dim(f"Task content (first 200 chars): {final_task[:200]}...")
                except Exception as err:
                    logger.error(str(err))
                    return 1
        elif opts["task"] and opts["task_file"]:
            logger.warn("Both --task and --task-file provided; --task-file takes precedence.")

        # ── Backup user prompt (if a task was provided) ──────────────────────
        if final_task and not opts["interactive"]:
            try:
                backup.backup_user_prompt(final_task)
                logger.dim(f"User prompt backed up to session: {backup.get_backup_dir()}")
            except Exception as err:
                logger.warn(f"Failed to backup user prompt: {err}")

        # ── Final validation: task or interactive mode ───────────────────────
        if not opts["interactive"] and not final_task:
            logger.warn("No task provided. Switching to interactive mode...\n")
            opts["interactive"] = True

        # ── Launch browser ───────────────────────────────────────────────────
        try:
            await agent.init()
        except Exception as err:
            logger.error(f"Failed to launch browser: {err}")
            if config.DEBUG:
                traceback.print_exc()
            return 1

        # ── Run ───────────────────────────────────────────────────────────────
        try:
            if opts["interactive"]:
                await agent.run_interactive()
            else:
                await agent.run(final_task)
        except Exception as err:
            logger.error(f"Agent error: {err}")
            if config.DEBUG:
                traceback.print_exc()
            exit_code = 1

    except asyncio.CancelledError:
        print("")
        logger.info("Shutting down...")
        exit_code = 0
    finally:
        try:
            await agent.shutdown()
        except Exception:
            pass

    return exit_code


def main() -> None:
    try:
        exit_code = asyncio.run(_async_main())
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
