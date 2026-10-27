"""agent.py — The core agent loop that ties everything together."""
from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import backup, logger
from .browser import DeepSeekBrowser
from .config import config
from .parser import parse_response
from .prompt import ConversationManager
from .tools import execute_tool

EXCLUDE_DIR_NAMES = {"node_modules", ".git", "dist", ".next", "build"}


class DeepSeekAgent:
    def __init__(self, save_log: bool = False) -> None:
        self.browser = DeepSeekBrowser()
        self.conversation = ConversationManager()
        self.save_log = save_log
        self._running = False

        session_id = f"session_{int(time.time() * 1000)}_{_rand_token()}"
        backup.set_session_id(session_id)
        logger.info(f"Backup session ID: {session_id}")

    # ── Public API ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        await self.browser.launch()
        await self.browser.new_chat()

    async def shutdown(self) -> None:
        await self.browser.close()

    async def run(self, task: str) -> str:
        self._running = True
        max_iter = config.MAX_ITERATIONS

        try:
            backup.backup_user_prompt(task)
            logger.dim(f"User prompt backed up to session: {backup.get_backup_dir()}")
        except Exception as err:
            logger.warn(f"Failed to backup user prompt: {err}")

        dir_listing = self._get_working_dir_listing()

        preview = task[:80] + ("…" if len(task) > 80 else "")
        logger.header(f"Task: {preview}")

        first_msg = self.conversation.build_first_message(task, dir_listing)

        if config.DEBUG:
            logger.dim("--- First message (truncated) ---")
            logger.dim(first_msg[:600] + "...")

        logger.info("Sending task to DeepSeek...")
        await self.browser.send_message(first_msg)

        for iter_n in range(1, max_iter + 1):
            logger.iteration(iter_n, max_iter)

            raw_response = await self.browser.wait_for_response()

            if not raw_response or not raw_response.strip():
                logger.warn("Empty response received — retrying...")
                await self.browser.send_message(
                    "Hãy tiếp tục. Nếu bạn đang chờ input, hãy tự đưa ra quyết định hợp lý nhất."
                )
                continue

            if config.DEBUG:
                logger.dim(f"--- Raw response ({len(raw_response)} chars) ---")
                logger.dim(raw_response[:400])

            self.conversation.add_assistant_message(raw_response)

            parsed = parse_response(raw_response)

            # ── Case 1: Tool call ──────────────────────────────────────────
            if parsed["type"] == "tool_call":
                logger.tool_call(parsed["name"], parsed["args"])

                is_error = False
                try:
                    result = await execute_tool(parsed["name"], parsed["args"])

                    if isinstance(result, dict) and result.get("__ask_user") is True:
                        logger.info(f"\n🤖 AI asks: {result['question']}")
                        user_response = await self._prompt_user(result["question"], result.get("options"))
                        feedback_msg = self.conversation.add_tool_result(parsed["name"], user_response, False)
                        await self.browser.send_message(feedback_msg)
                        continue

                    logger.tool_result(result)
                except Exception as err:
                    result = f"Error: {err}"
                    is_error = True
                    logger.tool_result(result, True)

                feedback_msg = self.conversation.add_tool_result(parsed["name"], result, is_error)
                await self.browser.send_message(feedback_msg)
                continue

            # ── Case 2: Parse error ─────────────────────────────────────────
            if parsed["type"] == "error":
                logger.warn(f"Parse error: {parsed['message']}")
                recovery = self.conversation.add_tool_result(
                    "SYSTEM",
                    f"Lỗi phân tích cú pháp: {parsed['message']}\n\nHãy thử lại với JSON hợp lệ trong tool call của bạn.",
                    True,
                )
                await self.browser.send_message(recovery)
                continue

            # ── Case 3: Final response ───────────────────────────────────────
            if parsed["type"] == "final":
                content = parsed["content"]
                looks_like_tool_call = (
                    re.search(r"tool_call", content, re.IGNORECASE)
                    or re.search(r'"name"\s*:\s*"[\w_]+"', content)
                    or re.search(r"write_file|read_file|run_command|list_directory", content[:200], re.IGNORECASE)
                )

                if looks_like_tool_call and self.conversation.turn_count <= max_iter - 2:
                    logger.warn("Response looks like a tool call but was not parsed — asking AI to retry format...")
                    retry = self.conversation.add_tool_result(
                        "SYSTEM",
                        "Phản hồi của bạn có vẻ chứa một tool call nhưng không thể phân tích được. "
                        "Hãy trả lời CHỈ bằng một khối code ```tool_call và không có gì khác — "
                        "không có văn bản trước hoặc sau nó.",
                        True,
                    )
                    await self.browser.send_message(retry)
                    continue

                logger.final_output(content)

                if self.save_log:
                    self._save_conversation_log(task, content)

                backups = backup.list_backups()
                if backups and config.DEBUG:
                    print("Backup manifest:")
                    for b in backups[-5:]:
                        backup_name = Path(b["backupPath"]).name if b.get("backupPath") else "(new file)"
                        print(f"  - {b.get('operation')}: {b.get('filePath')} → {backup_name}")
                    if len(backups) > 5:
                        print(f"  ... and {len(backups) - 5} more")

                self._running = False
                return content

        self._running = False
        warning = f"⚠ Reached maximum iterations ({max_iter}). The task may be incomplete."
        logger.warn(warning)
        return warning

    # ── Interactive (REPL) Mode ──────────────────────────────────────────────

    async def run_interactive(self) -> None:
        logger.header("Interactive Mode — Type your task and press Enter")
        logger.info('Commands: "exit" or "quit" to stop, "new" to start a new chat\n')

        loop = asyncio.get_event_loop()

        while True:
            try:
                task = (await loop.run_in_executor(None, lambda: input("\n\x1b[96m❯ Task:\x1b[0m "))).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not task:
                continue

            if task.lower() in ("exit", "quit", "q"):
                logger.info("Exiting...")
                break

            if task.lower() == "new":
                logger.info("Starting new chat...")
                await self.browser.new_chat()
                self.conversation = ConversationManager()
                continue

            try:
                await self.run(task)
            except Exception as err:
                logger.error(f"Task failed: {err}")
                if config.DEBUG:
                    import traceback
                    traceback.print_exc()

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _prompt_user(self, question: str, options: list | None = None) -> str:
        loop = asyncio.get_event_loop()

        def _ask() -> str:
            print("\n" + "=" * 60)
            print(f"📝 {question}")
            if options:
                print("\nOptions:")
                for i, opt in enumerate(options):
                    print(f"  {i + 1}. {opt}")
                print("\n(Enter the number or type your response)")
            print("=" * 60)

            answer = input("\nYour response: ")

            if options:
                try:
                    num = int(answer)
                    if 1 <= num <= len(options):
                        return options[num - 1]
                except ValueError:
                    pass
            return answer

        return await loop.run_in_executor(None, _ask)

    def _get_working_dir_listing(self) -> str:
        try:
            lines: list[str] = []
            root = Path(config.WORKING_DIR)

            def walk(directory: Path, depth: int) -> None:
                if depth > 3 or len(lines) >= 80:
                    return
                try:
                    entries = sorted(directory.iterdir(), key=lambda p: p.name)
                except OSError:
                    return
                for entry in entries:
                    if len(lines) >= 80:
                        return
                    if entry.name in EXCLUDE_DIR_NAMES or entry.suffix == ".lock":
                        continue
                    rel = entry.relative_to(root)
                    lines.append(f"./{rel}")
                    if entry.is_dir() and depth < 3:
                        walk(entry, depth + 1)

            walk(root, 1)
            lines.sort()
            return "\n".join(lines[:80]) if lines else "(empty directory)"
        except Exception:
            return "(could not read directory)"

    def _save_conversation_log(self, task: str, final_response: str) -> None:
        try:
            logs_dir = Path.home() / ".deepseek-agent" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            log_file = logs_dir / f"session-{ts}.txt"
            content = "\n".join([
                "DeepSeek Agent — Session Log",
                f"Date: {datetime.now(timezone.utc).isoformat()}",
                f"Task: {task}",
                f"Working Dir: {config.WORKING_DIR}",
                "═" * 40,
                self.conversation.export_log(),
                "",
                "═" * 40,
                "FINAL RESPONSE:",
                final_response,
            ])

            log_file.write_text(content, encoding="utf-8")
            logger.dim(f"Conversation saved: {log_file}")
        except Exception as err:
            logger.warn(f"Could not save log: {err}")


def _rand_token() -> str:
    import string
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(8))
