#!/usr/bin/env python3
"""Render locked-in picks from an EDL as a coloured table.

Usage: python3 lockin.py <edl.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: lockin.py <edl.json>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"malformed json: {exc}", file=sys.stderr)
        return 3

    console = Console(force_terminal=True, width=120)

    ranges = data.get("ranges", [])
    target = data.get("target_runtime_s")
    tolerance_pct = 10
    total = sum(r.get("duration", r.get("duration_s", 0)) for r in ranges)

    mode = data.get("selection_mode", "")
    changelog = data.get("changelog_v2") or data.get("changelog", "")
    subtitle = f"[dim]{mode}[/]" if mode else ""
    if changelog:
        subtitle = (subtitle + "\n" if subtitle else "") + f"[dim]{changelog}[/]"
    if not subtitle:
        subtitle = "[dim]picks locked — review before rendering[/]"

    console.print(Panel(subtitle, title="[bold cyan]STEP 5 · Lock in picks[/]",
                        title_align="left", border_style="cyan", expand=False))

    table = Table(show_header=True, header_style="bold white",
                  border_style="dim", expand=False)
    table.add_column("Pick", justify="center", width=6, style="bold magenta")
    table.add_column("Beat")
    table.add_column("Dur", justify="right", width=9)

    for i, r in enumerate(ranges, start=1):
        dur = r.get("duration", r.get("duration_s", 0))
        table.add_row(str(i), r.get("beat", "—"), f"{dur:.2f}s")

    if target is not None:
        tol = target * tolerance_pct / 100
        in_tol = abs(total - target) <= tol
        mark = "✓" if in_tol else "✗"
        style = "bold green" if in_tol else "bold red"
        table.add_row("", Text("Total", style="bold"),
                      Text(f"{total:.2f}s {mark}", style=style))
    else:
        table.add_row("", Text("Total", style="bold"),
                      Text(f"{total:.2f}s", style="bold green"))

    console.print(table)

    console.print()
    console.print(
        "[bold]Render?[/]   "
        "[bold green]y[/] yes  ·  [bold yellow]n[/] revise  ·  [bold red]q[/] quit"
    )
    console.print("[magenta]▸[/]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
