"""NOTES.md helper — newest entry at top, grouped by UTC day."""
from datetime import datetime, timezone
from pathlib import Path

NOTES = Path(__file__).parent / "NOTES.md"
HEADER = "# Copytrade activity log\n\n_Auto-generated. Newest entry at top._\n"


def append_entry(title: str, lines: list) -> None:
    now = datetime.now(timezone.utc)
    day_header = f"## {now:%Y-%m-%d}"
    block = f"### {now:%H:%M} UTC — {title}\n" + "".join(f"- {l}\n" for l in lines)

    text = NOTES.read_text(encoding="utf-8") if NOTES.exists() else HEADER
    if not text.startswith("# Copytrade activity log"):
        text = HEADER + "\n" + text

    marker = day_header + "\n"
    if marker in text:
        # Insert right below today's header (newer entries above older ones).
        idx = text.index(marker) + len(marker)
        text = text[:idx] + "\n" + block + text[idx:]
    else:
        # New day: goes right after the file header, above older days.
        head_end = len(HEADER)
        text = text[:head_end] + "\n" + marker + "\n" + block + text[head_end:]

    NOTES.write_text(text, encoding="utf-8")
