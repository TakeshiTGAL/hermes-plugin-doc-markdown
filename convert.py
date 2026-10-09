"""Markdown conversion via one MarkItDown converter (plugins and LLM off).

A zip archive is refused before any converter runs. ``.docx``, ``.xlsx``, and
``.pptx`` go only to that format's converter, and only when the package part
is present. Every MarkItDown call runs in a worker process. The parent stops
that process at ``convert_timeout_seconds`` after the converters have loaded,
and stops a worker that never finishes loading at
``DEFAULT_WORKER_LOAD_TIMEOUT``. The worker is also stopped if it passes
``CONVERT_MEMORY_LIMIT_BYTES`` (Linux: ``RLIMIT_AS`` inside the worker;
macOS: the parent watches RSS).
"""

from __future__ import annotations

import importlib
import io
import json
import logging
import os
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from . import settings
from .errors import PluginError
from .paths import ALLOWED_EXTENSIONS, resolve_readable_file

logger = logging.getLogger(__name__)

# Package part that identifies a real Office file. Names only; members are not extracted.
_OFFICE_PART = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
}

# One converter class per extension. The archive converter is never imported.
_CONVERTER_SPEC = {
    ".docx": ("markitdown.converters._docx_converter", "DocxConverter"),
    ".xlsx": ("markitdown.converters._xlsx_converter", "XlsxConverter"),
    ".pptx": ("markitdown.converters._pptx_converter", "PptxConverter"),
    ".xls": ("markitdown.converters._xlsx_converter", "XlsConverter"),
    ".pdf": ("markitdown.converters._pdf_converter", "PdfConverter"),
    ".html": ("markitdown.converters._html_converter", "HtmlConverter"),
    ".htm": ("markitdown.converters._html_converter", "HtmlConverter"),
    ".csv": ("markitdown.converters._csv_converter", "CsvConverter"),
    ".json": ("markitdown.converters._plain_text_converter", "PlainTextConverter"),
    ".txt": ("markitdown.converters._plain_text_converter", "PlainTextConverter"),
    ".md": ("markitdown.converters._plain_text_converter", "PlainTextConverter"),
}

_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

# Fixed worker cap. Not a config key: a caller cannot raise it.
# 880 MiB. Linux applies this as RLIMIT_AS; macOS stops the worker when RSS exceeds it.
# Above the RSS a 5 MiB HTML file reaches in 8 seconds, and below the RSS a
# forged docx reaches well before that clock.
CONVERT_MEMORY_LIMIT_BYTES = 880 * 1024 * 1024

# Passed to the worker. Hermes and credential variables are not copied.
_PS = "/bin/ps" if os.path.exists("/bin/ps") else "ps"

_CHILD_ENV_ALLOW = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_NUMERIC",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "PYTHONSAFEPATH",
    # Hermes v0.21.6+ starts a bare Python with -I and hands dependency site-packages to children through
    # PYTHONPATH. Without it the worker cannot import markitdown. It holds paths, not credentials.
    "PYTHONPATH",
)


def _dependency_missing(reason: str) -> PluginError:
    return PluginError(
        "dependency_missing",
        "markitdown is not installed in this Hermes environment.",
        "Run `hermes plugins validate <plugin-dir> --install-deps` or reinstall the plugin so python_dependencies are prepared.",
        details={"reason": reason},
    )


CONVERT_NEXT_STEP = {
    "file": "Confirm the file opens in its native app, is not password-protected, and matches a supported type; then retry.",
}


def _conversion_failed(name: str, basename: str, *, subject: str = "file") -> PluginError:
    logger.warning("markitdown convert failed for %s: %s", basename, name)
    return PluginError(
        "conversion_failed",
        f"MarkItDown could not convert this {subject} ({name}).",
        CONVERT_NEXT_STEP[subject],
        details={"exception_type": name, "basename": basename},
    )


def _zip_refused(basename: str) -> PluginError:
    return PluginError(
        "zip_refused",
        "A zip archive is refused before conversion.",
        "Pass a .docx, .xlsx, or .pptx that contains that format's package part, or another allowlisted file that is not a zip.",
        details={"basename": basename},
    )


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PluginError(
            "bad_argument",
            f"{name} must be a positive integer.",
            f"Retry with {name} unset or a positive integer.",
        )
    return value


# Full local, end-of-central, and spanned signatures. The two bytes "PK" are not enough.
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_LOCAL_SIG = _ZIP_MAGICS[0]


def _has_zip_magic(prefix: bytes) -> bool:
    return any(prefix.startswith(magic) for magic in _ZIP_MAGICS)


def _starts_with_zip_magic(real: str) -> bool:
    try:
        with open(real, "rb") as handle:
            return _has_zip_magic(handle.read(4))
    except OSError:
        return False
_DATA_DESCRIPTOR = 0x08
_ZIP64_MAGIC = 0xFFFFFFFF
_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_CHARSET_TOKEN = re.compile(
    r"(charset\s*=\s*[\"']?)([A-Za-z0-9_.:-]+)",
    re.IGNORECASE,
)
_LOCAL_TEXT = {".txt", ".md", ".csv", ".json"}
_LOCAL_HTML = {".html", ".htm"}


def _local_uncompressed(handle, info: zipfile.ZipInfo) -> Optional[int]:
    """Uncompressed size stored in the local header, without inflating.

    None means the header does not carry a size (bit 3, or it could not be
    read). Callers then keep the central-directory size only.
    """
    try:
        handle.seek(info.header_offset)
        raw = handle.read(30)
    except OSError:
        return None
    if len(raw) < 30 or raw[:4] != _LOCAL_SIG:
        return None
    flag = struct.unpack_from("<H", raw, 6)[0]
    if flag & _DATA_DESCRIPTOR:
        return None
    uncomp = struct.unpack_from("<I", raw, 22)[0]
    if uncomp != _ZIP64_MAGIC:
        return uncomp
    name_len, extra_len = struct.unpack_from("<HH", raw, 26)
    try:
        handle.seek(info.header_offset + 30 + name_len)
        extra = handle.read(extra_len)
    except OSError:
        return None
    index = 0
    while index + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, index)
        index += 4
        blob = extra[index : index + size]
        index += size
        if header_id == 0x0001 and len(blob) >= 8:
            return struct.unpack_from("<Q", blob, 0)[0]
    return None


def _inspect_zip(real: str) -> Optional[Tuple[set, int, bool]]:
    """Names, size sum, and whether a local header disagrees.

    The sum is the larger of each member's central-directory ``file_size``
    and its local-header uncompressed size, when that header stores one.
    Members are not extracted. This function does not open nested members.
    """
    if not zipfile.is_zipfile(real):
        return None
    try:
        with open(real, "rb") as handle, zipfile.ZipFile(handle) as archive:
            infos = archive.infolist()
            names = {info.filename.replace("\\", "/") for info in infos}
            total = 0
            mismatch = False
            for info in infos:
                central = info.file_size
                local = _local_uncompressed(handle, info)
                if local is None:
                    total += central
                else:
                    if local != central:
                        mismatch = True
                    total += max(local, central)
    except (zipfile.BadZipFile, OSError):
        return None
    return names, total, mismatch


def _refuse_before_convert(real: str, limit_bytes: int) -> str:
    """Return the extension to convert, or raise. Does not call a converter."""
    ext = os.path.splitext(real)[1].lower()
    basename = os.path.basename(real)
    if ext == ".zip" or ext not in ALLOWED_EXTENSIONS:
        raise _zip_refused(basename)
    inspected = _inspect_zip(real)
    if ext in _OFFICE_PART:
        if inspected is None:
            logger.warning("markitdown convert failed for %s: %s", basename, "BadZipFile")
            raise PluginError(
                "conversion_failed",
                "This Office file is not a readable zip archive, so it was not converted (BadZipFile).",
                "Confirm the file opens in its native app, is not password-protected, and matches a supported type; then retry.",
                details={"exception_type": "BadZipFile", "basename": basename},
            )
        names, total, mismatch = inspected
        if _OFFICE_PART[ext] not in names:
            raise _zip_refused(basename)
        if mismatch and total <= limit_bytes:
            raise PluginError(
                "zip_refused",
                "The central directory and the local header disagree about uncompressed size, so the file was not converted.",
                "Pass a .docx, .xlsx, or .pptx whose zip headers agree, or another allowlisted file that is not a zip.",
                details={"basename": basename},
            )
        if total > limit_bytes:
            raise PluginError(
                "uncompressed_too_large",
                f"Uncompressed size is {total} bytes (limit {limit_bytes}). The archive was not expanded.",
                "Use a smaller file, or raise max_file_bytes in the plugin config if appropriate.",
                details={
                    "uncompressed_bytes": total,
                    "limit_bytes": limit_bytes,
                    "basename": basename,
                },
            )
        return ext
    if inspected is not None or _starts_with_zip_magic(real):
        raise _zip_refused(basename)
    return ext


def _load_converter(ext: str):
    module_name, class_name = _CONVERTER_SPEC[ext]
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise _dependency_missing(type(exc).__name__) from None
    return cls()


def warm_converters() -> None:
    """Import every converter this plugin can call, before the conversion clock starts."""
    seen: set[tuple[str, str]] = set()
    for ext, spec in _CONVERTER_SPEC.items():
        if spec in seen:
            continue
        seen.add(spec)
        _load_converter(ext)


def _stream_info(ext: str, path: str, charset: Optional[str] = None):
    try:
        from markitdown import StreamInfo
    except ImportError as exc:
        raise _dependency_missing(type(exc).__name__) from None
    filename = os.path.basename(path) if path else None
    return StreamInfo(
        extension=ext,
        mimetype=_MIME[ext],
        charset=charset,
        filename=filename,
        local_path=path or None,
    )


def _text_from_result(result: Any) -> str:
    text = getattr(result, "text_content", None)
    if text is None:
        text = getattr(result, "markdown", None)
    if text is None:
        text = str(result)
    return text if isinstance(text, str) else str(text)


def _unknown_charset(basename: str, label: str) -> PluginError:
    return PluginError(
        "encoding_unconfirmed",
        (
            f"This HTML file declares charset {label}, which this plugin does not know, "
            "so it was not converted."
        ),
        "Use a charset Python knows, a Shift_JIS-family label, or omit the meta charset and save the file as UTF-8.",
        details={"basename": basename, "charset": label},
    )


def _encoding_unconfirmed(basename: str, charset: str) -> PluginError:
    return PluginError(
        "encoding_unconfirmed",
        f"This local text file is not valid {charset}, so it was not converted.",
        "Save the file as UTF-8. For HTML, a meta charset may name a Shift_JIS-family label, which is read as cp932. This plugin does not guess a local text encoding.",
        details={"basename": basename, "charset": charset},
    )


def _normalize_local_text(ext: str, data: bytes, basename: str) -> Tuple[bytes, str]:
    """Return UTF-8 bytes and the charset to pass in. Never guess.

    HTML uses a meta charset (Shift_JIS-family labels become cp932). An unknown
    declared name is refused. With no meta tag the file must be UTF-8. The
    bytes are re-encoded so the parser cannot apply a different codec.
    Other local text is UTF-8 only.
    """
    from .charset_util import html_meta_label, normalize_charset

    if ext in _LOCAL_HTML:
        label = html_meta_label(data)
        if label is None:
            charset = "utf-8"
        else:
            charset = normalize_charset(label)
            if not charset:
                raise _unknown_charset(basename, label)
        try:
            text = data.decode(charset)
        except UnicodeDecodeError:
            raise _encoding_unconfirmed(basename, charset) from None
        head, tail = text[:8192], text[8192:]
        # Only a meta tag's charset attribute. Body text that says charset= stays.
        head = _META_TAG.sub(
            lambda match: _CHARSET_TOKEN.sub(
                lambda token: token.group(1) + "utf-8", match.group(0)
            ),
            head,
        )
        return (head + tail).encode("utf-8"), "utf-8"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise _encoding_unconfirmed(basename, "utf-8") from None
    return data, "utf-8"


def _run_one_converter(
    real: str,
    ext: str,
    *,
    charset: Optional[str] = None,
    body: Optional[bytes] = None,
) -> str:
    converter = _load_converter(ext)
    info = _stream_info(ext, "" if body is not None else real, charset=charset)
    try:
        source = io.BytesIO(body) if body is not None else open(real, "rb")
        with source:
            result = converter.convert(source, info)
    except PluginError:
        raise
    except Exception as exc:  # noqa: BLE001 — typed JSON, never leak file bytes
        raise _conversion_failed(type(exc).__name__, os.path.basename(real)) from None
    return _text_from_result(result)


def _reject_blank(text: str, basename: str, *, page: bool = False) -> str:
    """Empty or form-feed-only text is not a successful conversion."""
    del page
    if text.strip():
        return text
    next_step = (
        "The file may be image-only or empty; try OCR outside this plugin, "
        "or a different source file."
    )
    raise PluginError(
        "empty_output",
        "Conversion produced no Markdown text.",
        next_step,
        details={"basename": basename},
    )


def convert_file_with_one_converter(real: str, limit_bytes: int) -> str:
    """Convert one already-resolved file. Used by the worker. Never an archive walk."""
    ext = _refuse_before_convert(real, limit_bytes)
    body: Optional[bytes] = None
    charset: Optional[str] = None
    if ext in _LOCAL_HTML or ext in _LOCAL_TEXT:
        with open(real, "rb") as handle:
            raw = handle.read()
        body, charset = _normalize_local_text(ext, raw, os.path.basename(real))
    return _run_one_converter(real, ext, charset=charset, body=body)


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def _readline(proc: subprocess.Popen, timeout: float) -> Optional[bytes]:
    """Read one stdout line. None means the time limit expired."""
    holder: Dict[str, Any] = {}

    def _run() -> None:
        try:
            if proc.stdout is None:
                holder["line"] = b""
                return
            holder["line"] = proc.stdout.readline()
        except Exception as exc:  # noqa: BLE001
            holder["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None
    if "exc" in holder:
        return b""
    line = holder.get("line")
    return b"" if line is None else line


def _parse_worker_line(line: bytes, basename: str, subject: str) -> Dict[str, Any]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise _conversion_failed("WorkerOutput", basename, subject=subject)
    if not isinstance(payload, dict):
        raise _conversion_failed("WorkerOutput", basename, subject=subject)
    return payload


def _raise_worker_error(payload: Dict[str, Any]) -> None:
    error_type = payload.get("error_type") or "conversion_failed"
    message = payload.get("error") or "MarkItDown could not convert this file."
    next_step = payload.get("next_step") or (
        "Confirm the file opens in its native app, is not password-protected, "
        "and matches a supported type; then retry."
    )
    details = {
        key: value
        for key, value in payload.items()
        if key not in {"ok", "error", "error_type", "next_step", "text", "ready"}
        and value not in (None, "")
    }
    raise PluginError(str(error_type), str(message), str(next_step), details=details)


def _unit(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _conversion_timeout(seconds: int, basename: str) -> PluginError:
    return PluginError(
        "conversion_timeout",
        (
            f"Conversion hit the time limit of {_unit(seconds, 'second', 'seconds')} "
            "and the worker process was stopped."
        ),
        "Retry with a smaller file, or raise convert_timeout_seconds in the plugin config if appropriate.",
        details={"timeout_seconds": seconds, "basename": basename},
    )


def _load_timeout(seconds: int, basename: str) -> PluginError:
    return PluginError(
        "conversion_timeout",
        (
            f"The worker process did not finish loading within {_unit(seconds, 'second', 'seconds')} "
            "and was stopped."
        ),
        "Retry. If this keeps happening, the environment may be too slow to load the converters.",
        details={
            "timeout_seconds": seconds,
            "basename": basename,
            "phase": "load",
        },
    )


def child_environ() -> Dict[str, str]:
    """Environment for the worker. Credential and Hermes variables are omitted."""
    env = {key: os.environ[key] for key in _CHILD_ENV_ALLOW if os.environ.get(key)}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def apply_linux_address_limit() -> None:
    """Cap address space on Linux. macOS is stopped by the parent's RSS watch."""
    if not sys.platform.startswith("linux"):
        return
    import resource

    limit = CONVERT_MEMORY_LIMIT_BYTES
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError) as exc:
        raise MemoryError(str(exc)) from None


class _RssUnreadable(Exception):
    """The macOS RSS watch could not read the worker."""


def _group_rss_bytes(pid: int) -> int:
    """Sum RSS for the worker's process group. ``ps`` reports kibibytes."""
    try:
        out = subprocess.check_output(
            [_PS, "-o", "rss=", "-g", str(pid)],
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise _RssUnreadable(str(exc)) from None
    total = 0
    saw = False
    for line in out.splitlines():
        text = line.strip()
        if not text:
            continue
        if not text.isdigit():
            raise _RssUnreadable("ps returned a non-numeric RSS")
        saw = True
        total += int(text) * 1024
    if not saw:
        raise _RssUnreadable("ps returned no RSS")
    return total


def _conversion_memory(basename: str) -> PluginError:
    limit = CONVERT_MEMORY_LIMIT_BYTES
    return PluginError(
        "conversion_memory",
        (
            f"Conversion hit the memory limit of {limit} bytes "
            "and the worker process was stopped."
        ),
        "Retry with a smaller file. This memory limit is fixed and is not raised by max_file_bytes.",
        details={"memory_limit_bytes": limit, "basename": basename},
    )


def _memory_watch_failed(basename: str) -> PluginError:
    return PluginError(
        "memory_watch_failed",
        "The memory watch could not read the worker RSS, so the conversion was stopped.",
        "Retry where ps can report the worker RSS. On Linux the worker sets its own address limit.",
        details={"basename": basename},
    )


def _raise_if_memory_stopped(memory: Dict[str, bool], basename: str) -> None:
    if memory.get("watch_failed"):
        raise _memory_watch_failed(basename)
    if memory.get("hit"):
        raise _conversion_memory(basename)


def _run_worker(
    args: List[str],
    *,
    stdin_bytes: Optional[bytes],
    timeout_seconds: int,
    basename: str,
    subject: str,
) -> str:
    """Run one conversion in a child. The conversion clock starts after load."""
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "convert_worker.py")
    proc = subprocess.Popen(
        [sys.executable, worker] + args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=child_environ(),
    )
    memory = {"hit": False, "watch_failed": False}

    def _watch_rss() -> None:
        if sys.platform != "darwin":
            return
        while proc.poll() is None and not memory["hit"] and not memory["watch_failed"]:
            try:
                rss = _group_rss_bytes(proc.pid)
            except _RssUnreadable:
                if proc.poll() is not None:
                    return
                memory["watch_failed"] = True
                _kill_process_group(proc)
                return
            if rss > CONVERT_MEMORY_LIMIT_BYTES:
                memory["hit"] = True
                _kill_process_group(proc)
                return
            time.sleep(0.01)

    if sys.platform == "darwin":
        threading.Thread(target=_watch_rss, daemon=True).start()

    def _feed() -> None:
        # The child reads stdin only after it reports ready, so a body larger
        # than the pipe buffer would block this write. It runs off-thread.
        try:
            if proc.stdin is None:
                return
            if stdin_bytes:
                proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threading.Thread(target=_feed, daemon=True).start()
    # A full stderr pipe would stall the child before it can report ready.
    threading.Thread(
        target=lambda: proc.stderr.read() if proc.stderr is not None else None,
        daemon=True,
    ).start()
    load_seconds = settings.DEFAULT_WORKER_LOAD_TIMEOUT
    payload: Dict[str, Any] = {}
    try:
        first = _readline(proc, load_seconds)
        _raise_if_memory_stopped(memory, basename)
        if first is None:
            _kill_process_group(proc)
            raise _load_timeout(load_seconds, basename)
        ready = _parse_worker_line(first, basename, subject)
        if ready.get("ready") is not True:
            if ready.get("ok") is False:
                _raise_worker_error(ready)
            raise _conversion_failed("WorkerOutput", basename, subject=subject)
        second = _readline(proc, timeout_seconds)
        _raise_if_memory_stopped(memory, basename)
        if second is None:
            _kill_process_group(proc)
            raise _conversion_timeout(timeout_seconds, basename)
        payload = _parse_worker_line(second, basename, subject)
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
        else:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
    _raise_if_memory_stopped(memory, basename)
    if not payload.get("ok"):
        _raise_worker_error(payload)
    text = payload.get("text")
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return text


def start_conversion_worker(real: str, *, timeout_seconds: int, limit_bytes: int) -> str:
    """Convert one local path in a worker process."""
    return _run_worker(
        ["--", real, str(int(limit_bytes))],
        stdin_bytes=None,
        timeout_seconds=timeout_seconds,
        basename=os.path.basename(real),
        subject="file",
    )


def convert_local_file(
    path: str,
    *,
    max_chars: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Convert a guarded local file to Markdown. Raises PluginError on failure."""
    config_bytes = settings.max_file_bytes()
    if max_bytes is None:
        limit_bytes = config_bytes
    else:
        # A caller cannot raise the configured file cap.
        limit_bytes = min(_positive_int(max_bytes, "max_bytes"), config_bytes)
    config_chars = settings.max_output_chars()
    if max_chars is None:
        char_limit = config_chars
    else:
        # Values above the config are not an error; the cut stays at the config.
        char_limit = min(_positive_int(max_chars, "max_chars"), config_chars)

    real, size = resolve_readable_file(path, max_bytes=limit_bytes)
    _refuse_before_convert(real, limit_bytes)
    text = start_conversion_worker(
        real,
        timeout_seconds=settings.convert_timeout_seconds(),
        limit_bytes=limit_bytes,
    )
    text = _reject_blank(text, os.path.basename(real), page=False)

    body, truncated = _truncate(text, char_limit)
    # truncated, char_count, and error precede markdown so a 1500-character
    # preview still shows whether the text was cut.
    return {
        "ok": True,
        "truncated": truncated,
        "char_count": len(body),
        "error": None,
        "path": real,
        "basename": os.path.basename(real),
        "extension": os.path.splitext(real)[1].lower(),
        "size_bytes": size,
        "markdown": body,
        "engine": "markitdown",
        "markitdown_plugins": False,
        "llm_helpers": False,
    }
