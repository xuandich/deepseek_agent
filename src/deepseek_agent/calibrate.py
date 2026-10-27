#!/usr/bin/env python3
"""calibrate.py — Auto-detect DeepSeek UI selectors and help fix browser.py."""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

from .config import config

_DOM_INSPECT_SCRIPT = """() => {
    function isVisible(el) {
        const s = window.getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0' && el.offsetParent !== null;
    }

    function classify(el) {
        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            classes: el.className?.slice?.(0, 120) || null,
            placeholder: el.placeholder || null,
            ariaLabel: el.getAttribute('aria-label') || null,
            dataTestId: el.dataset?.testid || null,
            role: el.getAttribute('role') || null,
            visible: isVisible(el),
            text: (el.innerText || '').slice(0, 40).replace(/\\n/g, ' ') || null,
            type: el.getAttribute('type') || null,
        };
    }

    const inputs = Array.from(document.querySelectorAll('textarea, [contenteditable="true"]'))
        .map(classify);

    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
        .filter(isVisible)
        .map(classify)
        .slice(0, 30);

    const classFreq = {};
    document.querySelectorAll('*').forEach(el => {
        (el.getAttribute('class') || '').split(/\\s+/).forEach(c => {
            if (c.length > 2 && c.length < 50) {
                classFreq[c] = (classFreq[c] || 0) + 1;
            }
        });
    });
    const topClasses = Object.entries(classFreq)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 80)
        .map(([cls, n]) => ({ cls, n }));

    const suggestedInput = (
        inputs.find(i => i.placeholder?.toLowerCase().includes('message'))?.id ||
        inputs.find(i => i.placeholder?.toLowerCase().includes('ask'))?.id ||
        inputs.find(i => i.visible)?.id ||
        null
    );

    const sendBtn = buttons.find(b =>
        /send/i.test(b.ariaLabel || '') ||
        /send/i.test(b.text || '') ||
        /send/i.test(b.classes || '')
    );

    const stopBtn = buttons.find(b =>
        /stop/i.test(b.ariaLabel || '') ||
        /stop/i.test(b.text || '') ||
        /stop/i.test(b.classes || '')
    );

    const newChatBtn = buttons.find(b =>
        /new chat/i.test(b.ariaLabel || '') ||
        /new chat/i.test(b.text || '') ||
        /new.?chat/i.test(b.classes || '')
    );

    return {
        url: window.location.href,
        title: document.title,
        inputs,
        buttons,
        topClasses,
        suggestions: { suggestedInput, sendBtn, stopBtn, newChatBtn },
    };
}"""


async def _calibrate() -> None:
    print("\n🔬  DeepSeek Agent — Selector Calibration Tool\n")
    print("This tool opens DeepSeek, inspects the DOM, and prints out")
    print("the selectors that your browser.py should use.\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            config.SESSION_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print("→ Navigating to", config.DEEPSEEK_URL, "...")
        await page.goto(config.DEEPSEEK_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        print("→ Inspecting DOM...\n")

        report = await page.evaluate(_DOM_INSPECT_SCRIPT)

        sep = "─" * 40

        print(sep)
        print("URL   :", report["url"])
        print("Title :", report["title"])
        print(sep)

        print("\n📥  INPUT ELEMENTS:")
        if not report["inputs"]:
            print("  (none found — are you logged in?)")
        for i, el in enumerate(report["inputs"]):
            print(f"  [{i}] {el}")

        print("\n🔘  BUTTONS (visible, first 30):")
        for i, el in enumerate(report["buttons"]):
            print(f"  [{i}] {el}")

        print("\n🏷️  TOP CSS CLASSES:")
        for entry in report["topClasses"][:40]:
            print(f"  {str(entry['n']).rjust(4)}x  .{entry['cls']}")

        print("\n" + sep)
        print("🎯  SUGGESTED SELECTORS (update browser.py SEL dict):")
        print(sep)

        s = report["suggestions"]

        if s.get("suggestedInput"):
            print(f"  chatInput  : '#{s['suggestedInput']}'  (or use the id above)")
        if s.get("sendBtn"):
            btn = s["sendBtn"]
            sel = (
                f'button[aria-label="{btn["ariaLabel"]}"]' if btn.get("ariaLabel")
                else f'#{btn["id"]}' if btn.get("id")
                else f'.{(btn.get("classes") or "").split(" ")[0]}'
            )
            print(f"  sendButton : '{sel}'")
        if s.get("stopBtn"):
            btn = s["stopBtn"]
            sel = (
                f'button[aria-label="{btn["ariaLabel"]}"]' if btn.get("ariaLabel")
                else f'.{(btn.get("classes") or "").split(" ")[0]}'
            )
            print(f"  stopButton : '{sel}'")
        if s.get("newChatBtn"):
            btn = s["newChatBtn"]
            sel = (
                f'button[aria-label="{btn["ariaLabel"]}"]' if btn.get("ariaLabel")
                else f'.{(btn.get("classes") or "").split(" ")[0]}'
            )
            print(f"  newChat    : '{sel}'")

        print(sep)
        print("\n📸  Taking screenshot → /tmp/deepseek-calibrate.png")
        await page.screenshot(path="/tmp/deepseek-calibrate.png", full_page=False)

        print("\n✅  Calibration complete! Update src/deepseek_agent/browser.py SEL dict with the selectors above.")
        print("    Press Ctrl+C to exit.\n")

        # Keep browser open so the user can inspect manually
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass


def main() -> None:
    try:
        asyncio.run(_calibrate())
    except KeyboardInterrupt:
        pass
    except Exception as err:
        print(f"Calibration error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
