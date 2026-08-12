"""Small shared helpers used by more than one extractor."""


def rows_to_markdown_table(rows: list[list[str]], header: list[str] | None = None) -> str:
    """Render a list of row-lists as a GitHub-flavored markdown table.
    If `header` isn't given, the first row of `rows` is used as the header.
    """
    if header is None:
        if not rows:
            return ""
        header, rows = rows[0], rows[1:]

    def esc(cell) -> str:
        return str(cell if cell is not None else "").replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(esc(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)
