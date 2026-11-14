#!/usr/bin/env python3
"""Regenerate the progress section of README.md from status.json.

Usage: python tools/update_status.py
Edits only the text between the STATUS markers in README.md.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATUS = ROOT / "status.json"
README = ROOT / "README.md"
START, END = "<!-- STATUS:START -->", "<!-- STATUS:END -->"
ICON = {"done": "✅", "in-progress": "🔨", "partial": "🟡", "planned": "⬜"}
WIDTH = 20


def bar(items):
    """Text progress bar. Partial counts as half."""
    total = len(items)
    score = sum(1.0 if v == "done" else 0.5 if v in ("partial", "in-progress") else 0 for v in items)
    pct = score / total if total else 0
    filled = round(pct * WIDTH)
    return f"`{'█' * filled}{'░' * (WIDTH - filled)}` {pct * 100:3.0f}%"


def counts(items):
    return ", ".join(f"{sum(v == k for v in items)} {k}" for k in ("done", "in-progress", "partial", "planned") if any(v == k for v in items))


def render(data):
    cats = data["categories"]
    every = [v for c in cats.values() for v in c.values()]
    lines = [
        "### ark-tools parity",
        "",
        f"**Overall:** {bar(every)} ({len(every)} commands: {counts(every)})",
        "",
        "| Category | Progress | Commands |",
        "|---|---|---|",
    ]
    for name, cmds in cats.items():
        cells = " ".join(f"{ICON[s]}&nbsp;`{c}`" for c, s in cmds.items())
        lines.append(f"| {name} | {bar(list(cmds.values()))} | {cells} |")

    extra = data.get("beyond_ark_tools", {})
    if extra:
        vals = list(extra.values())
        lines += [
            "",
            "### Beyond ark-tools",
            "",
            f"**Overall:** {bar(vals)} ({counts(vals)})",
            "",
        ]
        lines += [f"- {ICON[s]} {name}" for name, s in extra.items()]

    lines += ["", "✅ done · 🔨 in progress · 🟡 partial (exists in old scripts, not fully ported) · ⬜ planned. In-progress and partial count as half on the bars."]
    return "\n".join(lines)


def main():
    data = json.loads(STATUS.read_text(encoding="utf-8"))
    text = README.read_text(encoding="utf-8")
    block = f"{START}\n{render(data)}\n{END}"
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"README.md is missing the {START} / {END} markers")
    README.write_text(pattern.sub(lambda _: block, text), encoding="utf-8")
    print("README.md progress section updated.")


if __name__ == "__main__":
    main()
