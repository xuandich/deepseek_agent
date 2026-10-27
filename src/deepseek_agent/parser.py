"""parser.py — Parse DeepSeek's text responses to extract tool calls."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_response(raw_text: str) -> dict:
    """Parse a raw DeepSeek response string.

    Returns one of:
      {"type": "tool_call", "name": str, "args": dict, "raw": str}
      {"type": "final",     "content": str,             "raw": str}
      {"type": "error",     "message": str,             "raw": str}
    """
    text = strip_thinking_blocks(raw_text).strip()

    # ── Strategy 0 (DOM FALLBACK): bare "tool_call\n{ ... }" ────────────────
    bare_match = re.match(r"^tool_call\s*\n(.+)$", text, re.IGNORECASE | re.DOTALL)
    if bare_match:
        json_raw = bare_match.group(1).strip()
        try:
            parsed = json.loads(json_raw)
            name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
            args = parsed.get("args") or parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
            if name and isinstance(name, str):
                return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}
        except Exception:
            fixed = attempt_json_fix(json_raw)
            if fixed is not None:
                name = fixed.get("name") or fixed.get("tool") or fixed.get("function")
                args = fixed.get("args") or fixed.get("arguments") or fixed.get("parameters") or fixed.get("input") or {}
                if name:
                    return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}

    # ── Strategy 1 (PRIMARY): ```tool_call fenced code block ────────────────
    fenced_match = re.search(r"```tool_call\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        raw = fenced_match.group(1).strip()
        try:
            parsed = json.loads(raw)
            name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
            args = parsed.get("args") or parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
            if name and isinstance(name, str):
                return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}
        except Exception as e:
            fixed = attempt_json_fix(raw)
            if fixed is not None:
                name = fixed.get("name") or fixed.get("tool") or fixed.get("function")
                args = fixed.get("args") or fixed.get("arguments") or fixed.get("parameters") or fixed.get("input") or {}
                if name:
                    return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}
            return {
                "type": "error",
                "message": f"tool_call block had invalid JSON: {e}\nContent: {raw[:300]}",
                "raw": raw_text,
            }

    # ── Strategy 2: ```json block with "name"/"tool" key ─────────────────────
    json_fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_fence_match:
        try:
            parsed = json.loads(json_fence_match.group(1))
            name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
            args = parsed.get("args") or parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
            if name and isinstance(name, str):
                return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}
        except Exception:
            pass

    # ── Strategy 3: XML <tool_call> ───────────────────────────────────────────
    xml_match = re.search(
        r"<tool_call[^>]*>\s*(?:<name>(.*?)</name>\s*)?(?:<input>(.*?)</input>|<args>(.*?)</args>)\s*</tool_call>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if xml_match:
        name = (xml_match.group(1) or "").strip()
        input_raw = strip_code_fences((xml_match.group(2) or xml_match.group(3) or "").strip())
        if name:
            return try_parse_tool_call(name, input_raw, raw_text)

    # ── Strategy 4: XML with angle-brackets stripped by DOM ───────────────────
    dom_stripped_match = re.search(
        r"tool_call\s+name\s+([\w_]+)\s*/name\s+input\s*(.*?)\s*/input\s*/tool_call",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if dom_stripped_match:
        name = dom_stripped_match.group(1).strip()
        input_raw = strip_code_fences(dom_stripped_match.group(2).strip())
        return try_parse_tool_call(name, input_raw, raw_text)

    # ── Strategy 5: Any JSON object with "name" key anywhere in text ─────────
    if re.search(r"""["'](?:name|tool|function)["']\s*:\s*["'][\w_]+["']""", text):
        json_obj = extract_largest_json_object(text)
        if json_obj:
            name = json_obj.get("name") or json_obj.get("tool") or json_obj.get("function")
            args = json_obj.get("args") or json_obj.get("arguments") or json_obj.get("parameters") or json_obj.get("input") or {}
            if name and isinstance(name, str):
                return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}

    # ── Strategy 6: Python-style function call in code block ─────────────────
    func_match = re.search(r"```\w*\s*([\w_]+)\(([^)]*)\)\s*```", text)
    if func_match:
        name = func_match.group(1)
        args_raw = func_match.group(2)
        args: dict[str, Any] = {}
        arg_re = re.compile(
            r"""(\w+)\s*=\s*(?:"([^"]*?)"|'([^']*?)'|(\d+(?:\.\d+)?)|(\btrue\b|\bfalse\b))"""
        )
        for m in arg_re.finditer(args_raw):
            key = m.group(1)
            if m.group(2) is not None:
                args[key] = m.group(2)
            elif m.group(3) is not None:
                args[key] = m.group(3)
            elif m.group(4) is not None:
                args[key] = float(m.group(4)) if "." in m.group(4) else int(m.group(4))
            elif m.group(5) is not None:
                args[key] = m.group(5) == "true"
        if args:
            return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}

    # ── No tool call detected — final prose response ──────────────────────────
    return {"type": "final", "content": text, "raw": raw_text}


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def try_parse_tool_call(name: str, input_raw: str, raw_text: str) -> dict:
    try:
        args = json.loads(input_raw)
        return {"type": "tool_call", "name": name, "args": args, "raw": raw_text}
    except Exception as e:
        fixed = attempt_json_fix(input_raw)
        if fixed is not None:
            return {"type": "tool_call", "name": name, "args": fixed, "raw": raw_text}
        return {
            "type": "error",
            "message": f'Tool "{name}" returned invalid JSON: {e}\nRaw input: {input_raw[:200]}',
            "raw": raw_text,
        }


def strip_code_fences(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def strip_thinking_blocks(text: str) -> str:
    text = re.sub(r"<think>.*?</think>\n?", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^Thinking\.{0,3}\n.*?\n\n", "", text, count=1, flags=re.MULTILINE | re.DOTALL)
    return text.strip()


def attempt_json_fix(s: str):
    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", s)
        fixed = re.sub(r'([{,]\s*)(\w+)\s*:', r'\1"\2":', fixed)
        return json.loads(fixed)
    except Exception:
        return None


def extract_largest_json_object(text: str):
    """Extract the largest valid JSON object from a string using bracket counting."""
    best = None
    best_len = 0

    n = len(text)
    for i in range(n):
        if text[i] != "{":
            continue
        depth = 0
        in_str = False
        escape = False

        for j in range(i, n):
            ch = text[j]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[i:j + 1]
                    if len(candidate) > best_len:
                        try:
                            parsed = json.loads(candidate)
                            best = parsed
                            best_len = len(candidate)
                        except Exception:
                            fixed = attempt_json_fix(candidate)
                            if fixed is not None and len(candidate) > best_len:
                                best = fixed
                                best_len = len(candidate)
                    break

    return best


def format_tool_result(tool_name: str, result, is_error: bool = False) -> str:
    status = "ERROR" if is_error else "SUCCESS"
    return "\n".join([
        f"[TOOL RESULT: {tool_name} | {status}]",
        str(result),
        "[END TOOL RESULT]",
    ])


def is_asking_question(text: str) -> bool:
    patterns = [
        r"\?(\s*$)",
        r"could you (please |kindly )?clarify",
        r"can you provide more",
        r"what (do you|would you) (want|like|prefer)",
        r"please (specify|clarify|tell me)",
    ]
    return any(re.search(p, text, re.IGNORECASE | re.MULTILINE) for p in patterns)
