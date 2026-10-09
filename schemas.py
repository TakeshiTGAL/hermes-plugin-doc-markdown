"""Tool schemas: what the model reads to decide which tool to call and how."""

CONVERT = {
    "name": "doc_convert",
    "description": (
        "Convert a local file to Markdown: path='/home/me/docs/report.pdf'. "
        "Reads one absolute local path "
        "(PDF/DOCX/PPTX/XLSX/XLS (best-effort)/HTML/CSV/JSON/TXT/MD), built on "
        "Microsoft's MarkItDown, with third-party plugins "
        "and LLM caption/transcription off. After realpath, any absolute path "
        "with an allowlisted extension that this Hermes process can open may be "
        "read. It refuses the Hermes home, any path component that starts with "
        "'.', a relative path, an http, https, or file URL in any letter case, "
        "a missing file, and a directory, plus size and type checks. This is "
        "not a chroot or user-home sandbox. A zip archive is refused before "
        "conversion. A .docx, .xlsx, or .pptx is passed only to that format's "
        "converter. After the worker loads, conversion stops at "
        "convert_timeout_seconds (default 8) or at 922746880 bytes of memory. "
        "Loading stops at 60 seconds. That worker is not a sandbox for a "
        "hostile file. This tool does not fetch pages."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute local file path to convert "
                    "(example: /home/me/docs/report.pdf)."
                ),
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    "Optional positive integer. The cut is the smaller of this value "
                    "and max_output_chars (default 200000). A larger value is not an "
                    "error. 0 or below is refused."
                ),
            },
        },
        "required": ["path"],
    },
}

ALL_SCHEMAS = [CONVERT]
