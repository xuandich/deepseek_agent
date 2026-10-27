"""logger.py — ANSI-colored terminal output (no dependencies)."""
from __future__ import annotations

import json
import sys

_A = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
    "gray": "\x1b[90m",
    "lred": "\x1b[91m",
    "lgreen": "\x1b[92m",
    "lyellow": "\x1b[93m",
    "lblue": "\x1b[94m",
    "lmagenta": "\x1b[95m",
    "lcyan": "\x1b[96m",
}


def _c(code: str, text: str) -> str:
    return f"{_A[code]}{text}{_A['reset']}"


def _cb(code: str, text: str) -> str:
    return f"{_A['bold']}{_A[code]}{text}{_A['reset']}"


def _trunc_display(s, max_len: int = 400) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[:max_len] + _c("gray", f"… (+{len(s) - max_len} chars)")


def _json_preview(obj, max_len: int = 350) -> str:
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    return _trunc_display(s, max_len)


def banner() -> None:
    print(f"""
{_c('cyan', '╔══════════════════════════════════════════════════╗')}
{_c('cyan', '║')}   {_cb('lcyan', '🤖  DeepSeek Browser Agent')}                     {_c('cyan', '║')}
{_c('cyan', '║')}   {_c('gray', 'AI Coding Agent via Browser Automation')}         {_c('cyan', '║')}
{_c('cyan', '║')}   {_c('gray', 'No API key needed — uses chat.deepseek.com')}     {_c('cyan', '║')}
{_c('cyan', '╚══════════════════════════════════════════════════╝')}
""")


def header(msg: str) -> None:
    line = "─" * 50
    print(f"\n{_c('blue', line)}")
    print(f"{_c('bold', '📋 ')}{_cb('white', msg)}")
    print(f"{_c('blue', line)}\n")


def info(msg: str) -> None:
    print(f"{_c('lblue', '  ℹ ')} {msg}")


def success(msg: str) -> None:
    print(f"{_c('lgreen', '  ✓ ')} {_c('lgreen', msg)}")


def warn(msg: str) -> None:
    print(f"{_c('lyellow', '  ⚠ ')} {_c('lyellow', msg)}")


def error(msg: str) -> None:
    print(f"{_c('lred', '  ✗ ')} {_c('lred', msg)}")


def dim(msg: str) -> None:
    print(f"{_A['dim']}    {msg}{_A['reset']}")


def thinking(msg: str) -> None:
    """Spinner-style line (overwrites itself with \\r)."""
    sys.stdout.write(f"  {_c('cyan', '⟳')} {_c('gray', msg)}\r")
    sys.stdout.flush()


def clear_line() -> None:
    sys.stdout.write(f"\r{' ' * 80}\r")
    sys.stdout.flush()


def tool_call(name: str, args) -> None:
    print(f"\n  {_cb('magenta', '⚡ TOOL CALL')} {_c('cyan', f'→ {name}')}")
    preview = _json_preview(args)
    if preview.strip():
        for line in preview.split("\n"):
            print(f"  {_c('gray', line)}")


def tool_result(result, is_error: bool = False) -> None:
    icon = _c("lred", "  ✗ Result:") if is_error else _c("lgreen", "  ✓ Result:")
    text = _trunc_display(str(result), 300)
    color = "lred" if is_error else "gray"
    print(icon)
    lines = text.split("\n")[:12]
    for line in lines:
        print(f"  {_c(color, line)}")
    if len(str(result).split("\n")) > 12:
        print(f"  {_c('gray', '  … (truncated for display)')}")
    print("")


def final_output(msg: str) -> None:
    line = "━" * 50
    print(f"\n{_c('lgreen', line)}")
    print(f"{_cb('lgreen', '✅  TASK COMPLETE')}")
    print(f"{_c('lgreen', line)}\n")
    print(msg)
    print("")


def separator(label: str = "") -> None:
    pad = f" {label} " if label else ""
    print(f"\n{_c('gray', '·' * 20 + pad + '·' * 20)}\n")


def iteration(n: int, max_n: int) -> None:
    print(f"\n{_c('gray', '  ┄')} {_c('dim', f'Step {n}/{max_n}')} {_c('gray', '┄')}")
