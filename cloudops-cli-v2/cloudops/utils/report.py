"""Saída padronizada dos módulos: tabela colorida no terminal, ou export CSV/JSON."""

from __future__ import annotations

import csv
import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def print_table(title: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        console.print(f"[bold green]{title}: nada encontrado.[/bold green]")
        return

    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(row.get(c, "")) for c in columns])
    console.print(table)


def export(rows: list[dict[str, Any]], path: str) -> None:
    if not rows:
        console.print("[yellow]Nada para exportar.[/yellow]")
        return

    if path.endswith(".json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=str, ensure_ascii=False)
    elif path.endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        console.print(f"[red]Formato não suportado para {path}. Use .json ou .csv[/red]")
        return

    console.print(f"[bold green]Relatório salvo em {path}[/bold green]")


def die(message: str) -> None:
    console.print(f"[bold red]Erro:[/bold red] {message}")
    sys.exit(1)
