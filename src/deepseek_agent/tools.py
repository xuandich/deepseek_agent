"""tools.py — All tools available to the AI agent."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from . import backup
from .config import config

EXCLUDE_DIRS = {"node_modules", ".git", "dist", "build", "debug", "release", "backups", "__pycache__", "venv", ".venv", ".idea", ".vscode"}


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def to_lf(s) -> str:
    """Normalize any line ending to LF (\\n)."""
    if not s:
        return ""
    return re.sub(r"\r\n|\r", "\n", str(s))


def read_file_normalized(file_path: Path) -> str:
    return to_lf(file_path.read_text(encoding="utf-8"))


def write_file_normalized(file_path: Path, content: str) -> None:
    file_path.write_text(to_lf(content), encoding="utf-8")


def append_file_normalized(file_path: Path, content: str) -> None:
    with file_path.open("a", encoding="utf-8") as f:
        f.write(to_lf(content))


def truncate(s, max_len: int | None = None) -> str:
    if max_len is None:
        max_len = config.MAX_OUTPUT_LENGTH
    if not s:
        return ""
    s = str(s)
    if len(s) <= max_len:
        return s
    half = max_len // 2
    return (
        s[:half]
        + f"\n\n⚠ [OUTPUT TRUNCATED — {len(s):,} chars total, showing first & last {half} chars]\n\n"
        + s[-half:]
    )


def resolve(file_path: str) -> Path:
    """Resolve a path relative to the working directory."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    return Path(config.WORKING_DIR) / p


def format_bytes(size: int) -> str:
    if size == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    k = 1024
    import math
    i = min(int(math.log(size, k)), len(units) - 1)
    return f"{size / (k ** i):.1f} {units[i]}"


def _glob_to_regex(glob: str) -> re.Pattern:
    escaped = re.escape(glob).replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(f"^{escaped}$", re.IGNORECASE)


def _should_exclude_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS or name.startswith(".git")


# ─────────────────────────────────────────────
#  Tool implementations
# ─────────────────────────────────────────────

async def _read_file(path: str, start_line: int | None = None, end_line: int | None = None, **_):
    abs_path = resolve(path)
    if not abs_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if abs_path.is_dir():
        raise IsADirectoryError(f"{path} is a directory")

    content = read_file_normalized(abs_path)
    lines = content.split("\n")
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        s = max(0, int(start_line or 1) - 1)
        e = int(end_line) if end_line is not None else total_lines
        sliced = lines[s:e]
        numbered = "\n".join(f"{s + i + 1}:{line}" for i, line in enumerate(sliced))
        return f"[{path} | lines {s + 1}–{e}]\n{truncate(numbered)}"

    numbered = "\n".join(f"{i + 1}:{line}" for i, line in enumerate(lines))
    return f"[{path} | {total_lines} lines]\n{truncate(numbered)}"


async def _write_file(path: str, content: str, **_):
    abs_path = resolve(path)
    try:
        backup.create_backup_with_metadata(abs_path, "write_file")
    except Exception as err:
        print(f"Backup failed for {path}: {err}")
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    write_file_normalized(abs_path, content)
    line_count = len(to_lf(content).split("\n"))
    size = len(to_lf(content).encode("utf-8"))
    return f"✓ Wrote {format_bytes(size)} ({line_count} lines) → {path}"


async def _append_to_file(path: str, content: str, **_):
    abs_path = resolve(path)
    try:
        backup.create_backup_with_metadata(abs_path, "append_to_file")
    except Exception as err:
        print(f"Backup failed for {path}: {err}")
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    append_file_normalized(abs_path, content)
    size = len(to_lf(content).encode("utf-8"))
    return f"✓ Appended {format_bytes(size)} to {path}"


async def _replace_in_file(path: str, find: str, replace: str, use_regex: bool = False, all_occurrences: bool = True, **_):
    abs_path = resolve(path)
    try:
        backup.create_backup_with_metadata(abs_path, "replace_in_file")
    except Exception as err:
        print(f"Backup failed for {path}: {err}")

    content = read_file_normalized(abs_path)
    original = content

    normalized_find = to_lf(find)
    normalized_replace = to_lf(replace)

    if use_regex:
        pattern = re.compile(normalized_find)
        content = pattern.sub(normalized_replace, content) if all_occurrences else pattern.sub(normalized_replace, content, count=1)
    elif all_occurrences:
        content = content.replace(normalized_find, normalized_replace)
    else:
        content = content.replace(normalized_find, normalized_replace, 1)

    if content == original:
        return f'⚠ No matches found for "{find}" in {path}'

    if use_regex:
        count = len(re.findall(normalized_find, original))
    else:
        count = original.count(normalized_find)

    write_file_normalized(abs_path, content)
    return f'✓ Replaced {count} occurrence(s) of "{find}" in {path}'


async def _delete_file(path: str, **_):
    abs_path = resolve(path)
    if not abs_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        backup.create_backup_with_metadata(abs_path, "delete_file")
    except Exception as err:
        print(f"Backup failed for {path}: {err}")
    abs_path.unlink()
    return f"✓ Deleted {path}"


async def _list_directory(path: str = ".", recursive: bool = False, show_hidden: bool = False, **_):
    abs_path = resolve(path)
    if not abs_path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not abs_path.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    if recursive:
        collected: list[str] = []
        for root, dirnames, filenames in os.walk(abs_path):
            dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d) and (show_hidden or not d.startswith("."))]
            for name in list(dirnames) + filenames:
                if not show_hidden and name.startswith("."):
                    continue
                collected.append(str(Path(root) / name))
        collected.sort()
        collected = collected[:300]
        return "\n".join(collected) if collected else "(empty)"

    entries = list(os.scandir(abs_path))
    visible = entries if show_hidden else [e for e in entries if not e.name.startswith(".")]
    visible.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

    if not visible:
        return f"(empty directory: {path})"

    lines = []
    for e in visible:
        if e.is_dir():
            lines.append(f"📁  {e.name}/")
        else:
            try:
                size = e.stat().st_size
                lines.append(f"📄  {e.name}  {format_bytes(size)}")
            except OSError:
                lines.append(f"📄  {e.name}")

    return f"[{path}] — {len(visible)} items\n" + "\n".join(lines)


async def _create_directory(path: str, **_):
    abs_path = resolve(path)
    abs_path.mkdir(parents=True, exist_ok=True)
    return f"✓ Created directory: {path}"


async def _move_file(source: str, destination: str, **_):
    src = resolve(source)
    dest = resolve(destination)
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return f"✓ Moved: {source} → {destination}"


async def _copy_file(source: str, destination: str, **_):
    src = resolve(source)
    dest = resolve(destination)
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return f"✓ Copied: {source} → {destination}"


async def _get_file_info(path: str, **_):
    abs_path = resolve(path)
    if not abs_path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    stat = abs_path.stat()
    import datetime as _dt
    info: Dict[str, Any] = {
        "path": str(abs_path),
        "type": "directory" if abs_path.is_dir() else "file",
        "size": stat.st_size,
        "size_human": format_bytes(stat.st_size),
        "modified": _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.timezone.utc).isoformat(),
        "created": _dt.datetime.fromtimestamp(stat.st_ctime, tz=_dt.timezone.utc).isoformat(),
        "permissions": f"0{oct(stat.st_mode & 0o777)[2:]}",
    }
    if abs_path.is_file():
        content = read_file_normalized(abs_path)
        info["lines"] = len(content.split("\n"))
        info["encoding"] = "utf-8"
    return json.dumps(info, indent=2, ensure_ascii=False)


async def _run_command(command: str, cwd: str | None = None, timeout: int = 60_000, env: dict | None = None, **_):
    work_dir = resolve(cwd) if cwd else Path(config.WORKING_DIR)
    merged_env = {**os.environ, **(env or {})}

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout / 1000,
        )
    except subprocess.TimeoutExpired as err:
        stdout = (err.stdout or "").strip()
        stderr = (err.stderr or "").strip()
        combined = "\n\n".join(filter(None, [stdout and f"STDOUT:\n{stdout}", stderr and f"STDERR:\n{stderr}"]))
        raise RuntimeError(f"Command timed out after {timeout}ms:\n{truncate(combined or str(err))}")

    if proc.returncode != 0:
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = "\n\n".join(filter(None, [stdout and f"STDOUT:\n{stdout}", stderr and f"STDERR:\n{stderr}"]))
        raise RuntimeError(f"Command failed (exit code {proc.returncode}):\n{truncate(combined or 'no output')}")

    result = (proc.stdout or "").strip()
    return truncate(result or "(command completed with no output)")


async def _find_files(pattern: str, directory: str = ".", exclude: str | None = None, **_):
    directory_path = resolve(directory)
    exclude_re = re.compile(exclude, re.IGNORECASE) if exclude else None

    matches: list[str] = []
    for root, dirnames, filenames in os.walk(directory_path):
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]
        for name in filenames:
            full_path = str(Path(root) / name)
            if _should_exclude_dir(Path(root).name):
                continue
            if exclude_re and exclude_re.search(full_path):
                continue
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                matches.append(full_path)

    matches.sort()
    matches = matches[:100]
    return "\n".join(matches) if matches else f'No files matching "{pattern}" in {directory}'


async def _search_in_files(
    pattern: str,
    directory: str = ".",
    file_pattern: str | None = None,
    case_sensitive: bool = False,
    context_lines: int = 2,
    **_,
):
    directory_path = resolve(directory)
    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)

    file_matcher = _glob_to_regex(file_pattern) if file_pattern else None

    results: list[str] = []
    max_results = 150
    max_file_size = 5 * 1024 * 1024

    for root, dirnames, filenames in os.walk(directory_path):
        if len(results) >= max_results:
            break
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]

        for name in filenames:
            if len(results) >= max_results:
                break
            if file_matcher and not file_matcher.match(name):
                continue

            full_path = Path(root) / name
            try:
                if full_path.stat().st_size > max_file_size:
                    continue
            except OSError:
                continue

            try:
                with full_path.open("rb") as f:
                    head = f.read(1024)
                if b"\x00" in head:
                    continue
            except OSError:
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            lines = re.split(r"\r?\n", content)
            for i, line in enumerate(lines):
                if len(results) >= max_results:
                    break
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines) - 1, i + context_lines)
                    context_parts = []
                    for j in range(start, end + 1):
                        prefix = ">>>" if j == i else "   "
                        context_parts.append(f"{prefix} {j + 1}: {lines[j]}")
                    rel_path = os.path.relpath(full_path, directory_path)
                    results.append(f"[{rel_path}:{i + 1}]\n" + "\n".join(context_parts) + "\n")

    if not results:
        return f"No matches found for: {pattern}"
    return truncate("\n".join(results).strip())


async def _ask_user(question: str, options: list | None = None, **_):
    return {"__ask_user": True, "question": question, "options": options or []}


def _read_url_sync(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DeepSeekAgent/1.0)",
            "Accept": "text/html,text/plain,application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")

    text = re.sub(r"<script[\s\S]*?</script>", "", data, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return truncate(text.strip())


async def _read_url(url: str, **_):
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _read_url_sync, url)
    except urllib.error.URLError as err:
        raise RuntimeError(f"URL fetch failed: {err}") from err


async def _write_files(files: list, **_):
    if not isinstance(files, list):
        raise ValueError('"files" must be an array of {path, content}')
    results = []
    for entry in files:
        file_path = entry["path"]
        content = entry["content"]
        abs_path = resolve(file_path)
        try:
            backup.create_backup_with_metadata(abs_path, "write_files")
        except Exception as err:
            print(f"Backup failed for {file_path}: {err}")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        write_file_normalized(abs_path, content)
        results.append(f"✓ {file_path}")
    return f"Wrote {len(results)} files:\n" + "\n".join(results)


# ─────────────────────────────────────────────
#  Tool registry
# ─────────────────────────────────────────────

TOOLS: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "description": "Đọc toàn bộ nội dung một file. Có thể chỉ đọc một khoảng dòng cụ thể.",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn tới file"},
            "start_line": {"type": "number", "required": False, "description": "Dòng bắt đầu đọc (đánh số từ 1)"},
            "end_line": {"type": "number", "required": False, "description": "Dòng kết thúc đọc (bao gồm dòng này)"},
        },
        "execute": _read_file,
    },
    "write_file": {
        "description": "Ghi (tạo mới hoặc ghi đè) một file với nội dung cho trước. Tự động tạo các thư mục cha nếu chưa có.",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn file đích"},
            "content": {"type": "string", "required": True, "description": "Toàn bộ nội dung cần ghi vào file"},
        },
        "execute": _write_file,
    },
    "append_to_file": {
        "description": "Nối thêm văn bản vào cuối một file đã có (hoặc tạo mới nếu chưa tồn tại).",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn file"},
            "content": {"type": "string", "required": True, "description": "Văn bản cần nối thêm"},
        },
        "execute": _append_to_file,
    },
    "replace_in_file": {
        "description": "Tìm và thay thế văn bản trong một file. Hỗ trợ mẫu regex.",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn file"},
            "find": {"type": "string", "required": True, "description": "Văn bản cần tìm"},
            "replace": {"type": "string", "required": True, "description": "Văn bản thay thế"},
            "use_regex": {"type": "boolean", "required": False, "description": 'Coi "find" là một mẫu regex (mặc định: false)'},
            "all_occurrences": {"type": "boolean", "required": False, "description": "Thay thế tất cả các lần xuất hiện (mặc định: true)"},
        },
        "execute": _replace_in_file,
    },
    "delete_file": {
        "description": "Xoá vĩnh viễn một file.",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "File cần xoá"},
        },
        "execute": _delete_file,
    },
    "list_directory": {
        "description": "Liệt kê file và thư mục con trong một thư mục, có thể đệ quy.",
        "parameters": {
            "path": {"type": "string", "required": False, "description": "Thư mục cần liệt kê (mặc định: thư mục làm việc)"},
            "recursive": {"type": "boolean", "required": False, "description": "Đệ quy vào các thư mục con (mặc định: false)"},
            "show_hidden": {"type": "boolean", "required": False, "description": "Bao gồm cả file ẩn bắt đầu bằng dấu . (mặc định: false)"},
        },
        "execute": _list_directory,
    },
    "create_directory": {
        "description": "Tạo một thư mục (và tất cả các thư mục cha cần thiết).",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn thư mục cần tạo"},
        },
        "execute": _create_directory,
    },
    "move_file": {
        "description": "Di chuyển hoặc đổi tên một file/thư mục.",
        "parameters": {
            "source": {"type": "string", "required": True, "description": "Đường dẫn nguồn"},
            "destination": {"type": "string", "required": True, "description": "Đường dẫn đích"},
        },
        "execute": _move_file,
    },
    "copy_file": {
        "description": "Sao chép một file sang vị trí mới.",
        "parameters": {
            "source": {"type": "string", "required": True, "description": "Đường dẫn file nguồn"},
            "destination": {"type": "string", "required": True, "description": "Đường dẫn file đích"},
        },
        "execute": _copy_file,
    },
    "get_file_info": {
        "description": "Lấy thông tin metadata của một file/thư mục (kích thước, ngày sửa đổi, số dòng, v.v.).",
        "parameters": {
            "path": {"type": "string", "required": True, "description": "Đường dẫn file hoặc thư mục"},
        },
        "execute": _get_file_info,
    },
    "run_command": {
        "description": "Thực thi một lệnh shell và trả về kết quả. Mặc định chạy trong thư mục làm việc.",
        "parameters": {
            "command": {"type": "string", "required": True, "description": "Lệnh shell cần chạy"},
            "cwd": {"type": "string", "required": False, "description": "Thư mục làm việc cho lệnh này"},
            "timeout": {"type": "number", "required": False, "description": "Thời gian chờ tối đa tính bằng mili-giây (mặc định: 60000)"},
            "env": {"type": "object", "required": False, "description": "Các biến môi trường bổ sung dạng key-value"},
        },
        "execute": _run_command,
    },
    "find_files": {
        "description": 'Tìm file theo mẫu tên (kiểu glob, ví dụ "*.js", "test_*").',
        "parameters": {
            "pattern": {"type": "string", "required": True, "description": 'Mẫu tên file (ví dụ "*.ts")'},
            "directory": {"type": "string", "required": False, "description": "Thư mục cần tìm (mặc định: thư mục làm việc)"},
            "exclude": {"type": "string", "required": False, "description": "Mẫu cần loại trừ khỏi kết quả"},
        },
        "execute": _find_files,
    },
    "search_in_files": {
        "description": "Tìm mẫu văn bản bên trong các file (giống grep -r). Trả về các dòng khớp kèm tên file.",
        "parameters": {
            "pattern": {"type": "string", "required": True, "description": "Văn bản hoặc regex cần tìm"},
            "directory": {"type": "string", "required": False, "description": "Thư mục cần tìm (mặc định: thư mục làm việc)"},
            "file_pattern": {"type": "string", "required": False, "description": 'Chỉ tìm trong các file khớp mẫu này (ví dụ "*.js")'},
            "case_sensitive": {"type": "boolean", "required": False, "description": "Tìm kiếm phân biệt hoa/thường (mặc định: false)"},
            "context_lines": {"type": "number", "required": False, "description": "Số dòng ngữ cảnh quanh mỗi kết quả khớp (mặc định: 2)"},
        },
        "execute": _search_in_files,
    },
    "ask_user": {
        "description": "Hỏi người dùng một câu hỏi và chờ họ trả lời. Hữu ích khi bạn cần làm rõ, xin phê duyệt, hoặc xin gợi ý từ người dùng.",
        "parameters": {
            "question": {"type": "string", "required": True, "description": "Câu hỏi cần hỏi người dùng"},
            "options": {"type": "array", "required": False, "description": 'Danh sách lựa chọn (tuỳ chọn) để người dùng chọn (ví dụ: ["Yes", "No", "Cancel"])'},
        },
        "execute": _ask_user,
    },
    "read_url": {
        "description": "Tải nội dung văn bản của một URL (hữu ích để đọc tài liệu, API, v.v.).",
        "parameters": {
            "url": {"type": "string", "required": True, "description": "URL đầy đủ cần tải (http hoặc https)"},
        },
        "execute": _read_url,
    },
    "write_files": {
        "description": "Ghi nhiều file cùng lúc — hữu ích để dựng khung project.",
        "parameters": {
            "files": {"type": "array", "required": True, "description": "Mảng các object {path, content}"},
        },
        "execute": _write_files,
    },
}


def get_tool_descriptions() -> str:
    blocks = []
    for name, tool in TOOLS.items():
        param_lines = "\n".join(
            f"    - {p_name} ({p['type']}{', BẮT BUỘC' if p.get('required') else ''}): {p.get('description', '')}"
            for p_name, p in tool.get("parameters", {}).items()
        )
        blocks.append(f"### {name}\n  {tool['description']}\n  Tham số:\n{param_lines}")
    return "\n\n".join(blocks)


async def execute_tool(name: str, args: dict):
    tool = TOOLS.get(name)
    if not tool:
        available = ", ".join(TOOLS.keys())
        raise ValueError(f'Unknown tool: "{name}". Available tools: {available}')
    return await tool["execute"](**(args or {}))
