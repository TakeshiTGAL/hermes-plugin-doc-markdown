"""doc-markdown: local document to Markdown.

Built on Microsoft's MarkItDown (MIT). Registers ``doc_convert`` (toolset
``doc_markdown``). v0.1 does not register a web extract provider.
"""

from . import schemas, settings, tools
from .version import __version__  # noqa: F401


def register(ctx) -> None:
    """Register the convert tool."""
    getter = getattr(ctx, "get_config", None)
    settings.bind_config(getter if callable(getter) else None)

    for schema in schemas.ALL_SCHEMAS:
        ctx.register_tool(
            name=schema["name"],
            toolset="doc_markdown",
            schema=schema,
            handler=tools.HANDLERS[schema["name"]],
            emoji="📄",
        )
