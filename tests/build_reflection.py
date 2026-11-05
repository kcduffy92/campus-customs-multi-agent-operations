"""Put the student's Problem 10 reflection into the Reflection tab of output/desk_tickets.html, word for word.

Source: docs/problem10_reflection.md (the student's own text, also logged in AI_prompts.md). Only the
Markdown markup is converted: headings, **bold**, `code` and paragraphs. No words are added, removed or
changed. Safe to run again; the tab content sits between <!-- P10:reflection --> markers.

Run: .venv/Scripts/python.exe tests/build_reflection.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "problem10_reflection.md"
DESK = ROOT / "output" / "desk_tickets.html"

CSS = """  /* ---------- Problem 10: Reflection tab ---------- */
  .reflection-board { --bc: var(--purple); padding: 26px clamp(18px, 4vw, 44px); max-width: 920px; margin-left: auto; margin-right: auto; }
  .reflection-board h2 { margin: 0; font: 700 clamp(20px, 3vw, 26px)/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase;
    color: var(--pink); text-shadow: 3px 3px 0 var(--pink-deep); }
  .reflection-board .refl-sub { margin: 6px 0 18px; font: 700 14px var(--mono); letter-spacing: .12em; color: var(--muted); text-transform: uppercase; }
  .reflection-board h3 { margin: 28px 0 10px; font: 700 15px/1.35 var(--mono); letter-spacing: .08em; color: var(--yellow); }
  .reflection-board p { margin: 0 0 14px; font-size: 16px; line-height: 1.7; }
  .reflection-board code { color: var(--cyan); background: #0c1b21; padding: 1px 6px; font-size: 14px; }
  .reflection-board .refl-author { margin-top: 24px; color: var(--muted); font-size: 13.5px; }
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def render(md: str) -> str:
    parts = []
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = block.strip().split("\n")
        first = lines[0]
        if first.startswith("# "):
            parts.append(f"<h2>{inline(first[2:])}</h2>")
            if len(lines) > 1 and lines[1].startswith("## "):
                parts.append(f'<p class="refl-sub">{inline(lines[1][3:])}</p>')
            continue
        if first.startswith("## "):
            parts.append(f'<p class="refl-sub">{inline(first[3:])}</p>')
            continue
        if first.startswith("### "):
            parts.append(f"<h3>{inline(first[4:])}</h3>")
            continue
        parts.append(f"<p>{inline(' '.join(l.strip() for l in lines))}</p>")
    return "\n        ".join(parts)


def main() -> None:
    body = render(SOURCE.read_text(encoding="utf-8"))
    block = (f'<!-- P10:reflection -->\n      <article class="reflection-board pixel-box">\n        {body}\n'
             f'        <p class="refl-author">Written by Kate Duffy for Problem 10, about the Problem 9 run recorded in the '
             f'ticket tabs and the Cash tab of this page.</p>\n      </article>\n      <!-- /P10:reflection -->')
    src = DESK.read_text(encoding="utf-8")
    marked = re.compile(r"<!-- P10:reflection -->.*?<!-- /P10:reflection -->", re.S)
    legacy = '<div class="later pixel-box">\n        <h2>Reflection</h2>\n        <p>Coming in a later level.</p>\n      </div>'
    if marked.search(src):
        src = marked.sub(lambda _: block, src, count=1)
    elif src.count(legacy) == 1:
        src = src.replace(legacy, block)
    else:
        raise SystemExit("Could not find the Reflection tab placeholder in desk_tickets.html.")
    if "/* ---------- Problem 10: Reflection tab ---------- */" not in src:
        anchor = "  @media (max-width: 960px) {"
        assert src.count(anchor) == 1
        src = src.replace(anchor, CSS + anchor)
    # The tab labels no longer say "Later level".
    src = src.replace('<span class="name">Cash</span><span class="tid">Later level</span>',
                      '<span class="name">Cash</span><span class="tid">Problem 9 ledger</span>')
    src = src.replace('<span class="name">Reflection</span><span class="tid">Later level</span>',
                      '<span class="name">Reflection</span><span class="tid">Problem 10</span>')
    DESK.write_text(src, encoding="utf-8")
    print(f"Reflection tab filled from {SOURCE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
