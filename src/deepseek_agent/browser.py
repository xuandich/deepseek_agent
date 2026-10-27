"""browser.py — Playwright controller for chat.deepseek.com."""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

from . import logger
from .config import config

# ─────────────────────────────────────────────────────────────────────────────
#  Selector banks — ordered by likelihood, with fallbacks
#  We never depend on a single selector; DeepSeek's UI can change.
# ─────────────────────────────────────────────────────────────────────────────

SEL = {
    "chatInput": [
        "#chat-input",
        "textarea[placeholder]",
        "textarea",
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ],
    "sendButton": [
        'button[aria-label*="Send" i]',
        'button[aria-label*="send" i]',
        '[data-testid="send-button"]',
        'button[type="submit"]',
        '[class*="send-btn"]',
        '[class*="sendBtn"]',
        '[class*="send-button"]',
    ],
    "stopButton": [
        'button[aria-label*="Stop" i]',
        '[aria-label*="stop generating" i]',
        '[data-testid="stop-button"]',
        '[class*="stop-btn"]',
        '[class*="stopBtn"]',
    ],
    "newChat": [
        'button[aria-label*="New chat" i]',
        'button[aria-label*="New conversation" i]',
        'a[href="/"][aria-label]',
        '[data-testid="new-chat"]',
        '[class*="new-chat"]',
        '[class*="newChat"]',
    ],
    "messageContainer": [
        '[class*="chat-content"]',
        '[class*="message-list"]',
        '[class*="conversation"]',
        "main",
    ],
}


class DeepSeekBrowser:
    def __init__(self) -> None:
        self._playwright = None
        self.context = None
        self.page = None
        self._closed = False
        self._display = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def launch(self) -> None:
        # Start the virtual display BEFORE the Playwright driver process, so the
        # driver (and the browser it spawns) inherits the virtual DISPLAY from
        # the very start, instead of whatever real DISPLAY was set beforehand.
        if config.VIRTUAL_DISPLAY and not config.HEADLESS:
            self._start_virtual_display()

        self._playwright = await async_playwright().start()
        await self._launch_managed()

        await self._navigate(config.DEEPSEEK_URL)
        await self._ensure_logged_in()

        logger.success("Browser ready!")

    def _start_virtual_display(self) -> None:
        """Start an Xvfb virtual display so the browser can run non-headless
        (avoiding headless-mode bot detection) without popping up a real window."""
        try:
            from pyvirtualdisplay import Display
        except ImportError as err:
            raise RuntimeError(
                "VIRTUAL_DISPLAY is enabled but pyvirtualdisplay is not installed. "
                "Run: uv add pyvirtualdisplay"
            ) from err

        logger.info("Starting virtual display (Xvfb)...")
        try:
            self._display = Display(visible=False, size=(1280, 900), backend="xvfb")
            self._display.start()
        except Exception as err:
            self._display = None
            raise RuntimeError(
                f"Could not start Xvfb virtual display: {err}\n"
                "  → Make sure Xvfb is installed (e.g. `sudo apt install xvfb`)."
            ) from err

        # Xvfb is an X11 server, so Chromium must actually be told to use X11.
        # On a Wayland session, Chromium auto-detects WAYLAND_DISPLAY and uses
        # the real Wayland compositor instead — ignoring DISPLAY entirely, which
        # would make the browser show up on the real screen regardless of Xvfb.
        os.environ.pop("WAYLAND_DISPLAY", None)

    async def _launch_managed(self) -> None:
        logger.info("Launching browser with persistent session...")

        session_dir = str(Path(config.SESSION_DIR).resolve())

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-default-apps",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        if self._display is not None:
            # Force the X11 backend so the browser actually renders into the
            # Xvfb virtual display instead of auto-detecting a real Wayland one.
            args.append("--ozone-platform=x11")

        self.context = await self._playwright.chromium.launch_persistent_context(
            session_dir,
            headless=config.HEADLESS,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            args=args,
            ignore_default_args=["--enable-automation"],
        )

        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()

        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        try:
            if self._display:
                self._display.stop()
        except Exception:
            pass

    # ── Navigation ─────────────────────────────────────────────────────────

    async def _navigate(self, url: str) -> None:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self.page.wait_for_timeout(1_500)
        except Exception as err:
            logger.warn(f"Navigation warning: {err}")

    async def new_chat(self) -> None:
        try:
            for sel in SEL["newChat"]:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await self.page.wait_for_timeout(1_000)
                        logger.dim("Started new chat session")
                        return
                except Exception:
                    pass
        except Exception:
            pass

        await self._navigate(config.DEEPSEEK_URL)
        logger.dim("Navigated to DeepSeek home (new chat)")

    # ── Login handling ─────────────────────────────────────────────────────

    async def _ensure_logged_in(self) -> None:
        await self.page.wait_for_timeout(2_000)

        needs_login = await self.page.evaluate(
            """() => {
                const url = window.location.href;
                const bodyText = document.body?.innerText || '';
                return (
                    url.includes('/auth') ||
                    url.includes('/login') ||
                    url.includes('/sign') ||
                    bodyText.includes('Sign in') ||
                    bodyText.includes('Log in') ||
                    !!document.querySelector('input[type="password"]')
                );
            }"""
        )

        if needs_login:
            self._print_login_banner()
            await self._wait_for_enter()
            await self.page.wait_for_timeout(2_000)

    def _print_login_banner(self) -> None:
        print("")
        logger.warn("╔══════════════════════════════════════════════╗")
        logger.warn("║  🔐  LOGIN REQUIRED                          ║")
        logger.warn("║                                              ║")
        logger.warn("║  1. Log in to DeepSeek in the browser window ║")
        logger.warn("║  2. Return here and press  ENTER  to continue║")
        logger.warn("╚══════════════════════════════════════════════╝")
        print("")

    async def _wait_for_enter(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: input())

    # ── Sending Messages ───────────────────────────────────────────────────

    async def send_message(self, text: str) -> None:
        el, is_textarea = await self._find_input()

        await el.click(force=True)
        await self.page.wait_for_timeout(200)

        await self.page.keyboard.press("Control+a")
        await self.page.wait_for_timeout(100)

        if is_textarea:
            await el.fill(text)
        else:
            await self.page.evaluate(
                """([element, content]) => {
                    element.focus();
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    document.execCommand('insertText', false, content);
                    element.dispatchEvent(new InputEvent('input', { bubbles: true, data: content }));
                }""",
                [el, text],
            )

        await self.page.wait_for_timeout(config.SEND_DELAY)

        clicked = await self._click_send_button()
        if not clicked:
            await self.page.keyboard.press("Enter")

        await self.page.wait_for_timeout(500)

    async def _find_input(self):
        for sel in SEL["chatInput"]:
            try:
                el = await self.page.wait_for_selector(sel, timeout=4_000, state="visible")
                if not el:
                    continue
                tag_name = await el.evaluate("e => e.tagName.toLowerCase()")
                is_content_editable = await el.evaluate("e => e.isContentEditable")
                return el, (tag_name == "textarea" and not is_content_editable)
            except Exception:
                pass
        raise RuntimeError(
            "Cannot find the DeepSeek chat input box.\n"
            "  → Make sure the page is fully loaded and you are logged in.\n"
            "  → Run with --debug to inspect DOM selectors.\n"
            "  → Run: deepseek-agent --calibrate to auto-detect selectors."
        )

    async def _click_send_button(self) -> bool:
        for sel in SEL["sendButton"]:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    return True
            except Exception:
                pass
        return False

    # ── Waiting for Response ───────────────────────────────────────────────

    async def wait_for_response(self) -> str:
        """
        Wait until DeepSeek finishes generating and return the response text.

        Algorithm:
         1. Record how many assistant messages are on the page right now.
         2. Wait until a new message appears (count goes up).
         3. Poll the last message text every 500 ms.
         4. When the text has not changed for STABLE_DELAY ms AND
            no stop/loading indicator is visible → done.
        """
        timeout = config.RESPONSE_TIMEOUT
        stable_delay = config.STABLE_DELAY
        start = time.monotonic() * 1000

        # ── Phase 1: wait for a new message to appear ──────────────────────
        initial_count = await self._get_message_count()
        appeared = False

        while (time.monotonic() * 1000) - start < 12_000:
            count = await self._get_message_count()
            if count > initial_count:
                appeared = True
                break
            await self.page.wait_for_timeout(400)

        if not appeared:
            logger.warn("Response may have been delayed — continuing to wait...")

        # ── Phase 2: wait for text to stabilise ────────────────────────────
        last_text = ""
        stable_start = None
        dot_count = 0

        while (time.monotonic() * 1000) - start < timeout:
            text = await self._extract_last_message()

            if text != last_text:
                last_text = text
                stable_start = None
            elif len(text) > 0:
                if stable_start is None:
                    stable_start = time.monotonic() * 1000
                elif (time.monotonic() * 1000) - stable_start >= stable_delay:
                    if not await self._is_generating():
                        break  # confirmed done
                    stable_start = None  # still generating, reset

            dot_count = (dot_count + 1) % 4
            logger.thinking(f"Receiving response{'.' * dot_count}  ({len(text)} chars)")

            await self.page.wait_for_timeout(500)

        logger.clear_line()

        final = await self._extract_last_message()
        return self._clean_text(final)

    # ── DOM Extraction ─────────────────────────────────────────────────────

    async def _get_message_count(self) -> int:
        return await self.page.evaluate(
            """() => {
                const candidates = [
                    '[class*="assistant"][class*="message"]',
                    '[data-role="assistant"]',
                    '[class*="markdown-content"]',
                    '.ds-markdown',
                    '[class*="chat-message"]',
                    '[class*="message-bubble"]',
                ];
                for (const sel of candidates) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) return els.length;
                }
                return document.querySelectorAll('[class*="message"]').length;
            }"""
        )

    async def _extract_last_message(self) -> str:
        return await self.page.evaluate(
            """() => {
                function getFullText(el) {
                    if (!el) return '';
                    let result = '';

                    function walk(node) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            result += node.textContent;
                            return;
                        }
                        if (node.nodeType !== Node.ELEMENT_NODE) return;
                        const tag = node.tagName.toLowerCase();

                        if (tag === 'pre') {
                            const codeEl = node.querySelector('code');
                            if (codeEl) {
                                const cls = codeEl.className || '';
                                const lang = (cls.match(/language-(\\S+)/) || [])[1] || '';
                                const body = codeEl.textContent || '';
                                result += '\\n```' + lang + '\\n' + body + '\\n```\\n';
                            } else {
                                result += '\\n```\\n' + node.textContent + '\\n```\\n';
                            }
                            return;
                        }

                        if (tag === 'code') {
                            const parentTag = node.parentElement && node.parentElement.tagName
                                ? node.parentElement.tagName.toLowerCase() : '';
                            if (parentTag !== 'pre') {
                                result += '`' + node.textContent + '`';
                            }
                            return;
                        }

                        for (const child of node.childNodes) walk(child);

                        if (['p','div','li','br','h1','h2','h3','h4','h5','h6'].includes(tag)) {
                            result += '\\n';
                        }
                    }

                    walk(el);
                    return result.trim();
                }

                const directSelectors = [
                    '.ds-markdown',
                    '[class*="assistant"] [class*="markdown"]',
                    '[class*="assistant"] [class*="content"]',
                    '[data-role="assistant"] [class*="content"]',
                    '[class*="ai-message"] [class*="content"]',
                    '[class*="bot-message"] [class*="content"]',
                    '[class*="response-content"]',
                    '[class*="message-content"]:last-child',
                ];

                for (const sel of directSelectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        const t = getFullText(els[els.length - 1]);
                        if (t.length > 10) return t;
                    }
                }

                const markdownEls = document.querySelectorAll(
                    '[class*="markdown"], [class*="prose"], [class*="rendered"]'
                );
                if (markdownEls.length > 0) {
                    const t = getFullText(markdownEls[markdownEls.length - 1]);
                    if (t.length > 10) return t;
                }

                const allBlocks = Array.from(
                    document.querySelectorAll('[class*="message"], [class*="chat-item"], [class*="turn"]')
                );
                const candidates = allBlocks.filter(el => {
                    const cls = el.className || '';
                    return (
                        !cls.toLowerCase().includes('input') &&
                        !cls.toLowerCase().includes('user') &&
                        !el.querySelector('textarea, input[type="text"]') &&
                        (el.innerText || '').length > 20
                    );
                });

                if (candidates.length > 0) {
                    return getFullText(candidates[candidates.length - 1]);
                }

                return '';
            }"""
        )

    async def _is_generating(self) -> bool:
        return await self.page.evaluate(
            """() => {
                const stopSelectors = [
                    'button[aria-label*="Stop" i]',
                    '[class*="stop-gen"]',
                    '[class*="stopGen"]',
                    '[class*="generating"]',
                ];
                for (const sel of stopSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const s = window.getComputedStyle(el);
                        if (s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0') return true;
                    }
                }

                const loaderSelectors = [
                    '[class*="typing"]',
                    '[class*="loading"]',
                    '[class*="spinner"]',
                    '[class*="blink"]',
                    '[class*="cursor"]',
                    '[class*="pulsing"]',
                    'svg[class*="loading"]',
                    'svg[class*="spinner"]',
                ];
                for (const sel of loaderSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const s = window.getComputedStyle(el);
                        if (s.display !== 'none' && s.visibility !== 'hidden') return true;
                    }
                }

                return false;
            }"""
        )

    # ── Text Cleanup ───────────────────────────────────────────────────────

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""

        text = re.sub(r"<think>.*?</think>\n?", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"^Thinking\.{0,3}\n.*?\n\n", "", text, count=1, flags=re.MULTILINE | re.DOTALL)
        text = re.sub(r"^\d+(?:Copy|Run|Insert|Edit)\b.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Debug / Calibration Utilities ───────────────────────────────────────

    async def dump_debug_info(self) -> None:
        info = await self.page.evaluate(
            """() => {
                const classFreq = {};
                document.querySelectorAll('*').forEach(el => {
                    el.classList.forEach(c => {
                        if (c.match(/message|chat|input|send|stop|markdown|content|assistant|user|bot/i)) {
                            classFreq[c] = (classFreq[c] || 0) + 1;
                        }
                    });
                });

                const inputs = Array.from(document.querySelectorAll('textarea, [contenteditable]')).map(e => ({
                    tag: e.tagName,
                    id: e.id || null,
                    class: e.className?.slice(0, 80) || null,
                    placeholder: e.placeholder || null,
                    editable: e.isContentEditable,
                    visible: e.offsetParent !== null,
                }));

                return {
                    url: window.location.href,
                    title: document.title,
                    classes: Object.entries(classFreq).sort((a, b) => b[1] - a[1]).slice(0, 40),
                    inputs,
                };
            }"""
        )

        print("\n" + "═" * 40)
        print("  DOM DEBUG INFO")
        print("═" * 40)
        print("URL   :", info["url"])
        print("Title :", info["title"])
        print("\nInput elements:")
        for i in info["inputs"]:
            print(" ", i)
        print("\nMatching CSS classes (by frequency):")
        for cls, count in info["classes"]:
            print(f"  {str(count).rjust(3)}x  .{cls}")
        print("═" * 40 + "\n")

    async def screenshot(self, file_path: str = "/tmp/deepseek-agent-debug.png") -> None:
        await self.page.screenshot(path=file_path, full_page=False)
        logger.info(f"Screenshot saved: {file_path}")
