"""
cloudops-cli - interface unica para as 5 ferramentas de gestao de cloud.

Um unico ponto de entrada, com subcomandos por ferramenta e um flag
--profile compartilhado por todos, que resolve qual provider/conta usar
a partir do config.yaml (~/.cloudops/config.yaml). Isso e o que facilita
as integracoes: trocar de conta AWS, projeto GCP ou subscription Azure
e so trocar o --profile, sem tocar em codigo.

Uso:
    cloudops idle-audit --profile aws-prod
    cloudops idle-audit --profile aws-prod --export relatorio.csv
    cloudops backup --profile aws-prod --volume vol-123 --to region:us-west-2
    cloudops creds check --profile aws-prod
    cloudops creds rotate --profile aws-prod --id AKIA...
    cloudops tags scan --profile aws-prod
    cloudops tags fix --profile aws-prod --resource-id i-123 --tags owner=max,environment=prod
    cloudops tfstate-audit --profile aws-prod --state terraform.tfstate
    cloudops profiles                       # lista profiles configurados
    cloudops menu                           # menu interativo (sem precisar decorar comandos)
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

from .config import load_config
from .modules import backup_sync, cred_rotator, idle_audit, tag_enforcer, tfstate_auditor
from .providers import build_provider
from .utils.report import die, export, print_table

app = typer.Typer(help="cloudops-cli - auditoria, backup, credenciais, tags e drift, multi-cloud.")
creds_app = typer.Typer(help="Gestao de credenciais/chaves de API.")
tags_app = typer.Typer(help="Enforcement de tags obrigatorias.")
app.add_typer(creds_app, name="creds")
app.add_typer(tags_app, name="tags")

console = Console()


def _get_provider(profile_name: Optional[str]):
    cfg = load_config()
    try:
        profile = cfg.get_profile(profile_name)
        return build_provider(profile), cfg
    except (KeyError, ValueError, ImportError) as exc:
        die(str(exc))
    except Exception as exc:
        resolved_profile = profile_name or cfg.defaults.get("profile")
        die(
            "Falha ao autenticar no provider: "
            + str(exc)
            + "\nVerifique as credenciais do profile '"
            + str(resolved_profile)
            + "' em "
            + str(cfg.raw_path)
            + " (ex.: aws configure --profile <nome>, gcloud auth, az login)."
        )


@app.command("profiles")
def list_profiles():
    """Lista os profiles configurados em ~/.cloudops/config.yaml."""
    cfg = load_config()
    rows = [
        {"profile": name, "provider": p.provider, "detalhes": {k: v for k, v in p.options.items() if k != "provider"}}
        for name, p in cfg.profiles.items()
    ]
    print_table(f"Profiles ({cfg.raw_path})", rows, ["profile", "provider", "detalhes"])


@app.command("idle-audit")
def idle_audit_cmd(
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
    export_path: Optional[str] = typer.Option(None, "--export", help="Salvar relatorio em .csv ou .json"),
):
    """Audita VMs paradas, discos sem anexo e IPs sem associacao; estima economia."""
    provider, _ = _get_provider(profile)
    rows = idle_audit.run(provider)
    print_table("Recursos ociosos", rows, ["tipo", "id", "nome", "regiao", "estado", "custo_mensal_estimado"])
    total = idle_audit.total_potential_savings(rows)
    console.print(f"\n[bold]Economia potencial estimada:[/bold] US$ {total}/mes\n")
    if export_path:
        export(rows, export_path)


@app.command("backup")
def backup_cmd(
    volume: str = typer.Option(..., help="ID do volume/disco a copiar"),
    to: str = typer.Option(..., help="Destino, ex.: region:us-west-2"),
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
):
    """Cria snapshot de um volume e copia para outra regiao/conta/bucket."""
    provider, _ = _get_provider(profile)
    result = backup_sync.run(provider, volume, to)
    print_table("Backup cruzado", [result], list(result.keys()))


@creds_app.command("check")
def creds_check_cmd(
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
    max_age_days: int = typer.Option(90, help="Idade maxima antes de marcar como vencida"),
):
    """Lista credenciais e sinaliza quais precisam ser rotacionadas."""
    provider, _ = _get_provider(profile)
    rows = cred_rotator.check_expiring(provider, max_age_days=max_age_days)
    print_table("Credenciais", rows, ["id", "tipo", "dono", "idade_dias", "expira_em_dias", "status"])


@creds_app.command("rotate")
def creds_rotate_cmd(
    id: str = typer.Option(..., "--id", help="ID da credencial a rotacionar"),
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
):
    """Rotaciona uma credencial e notifica via Slack (se configurado)."""
    provider, cfg = _get_provider(profile)
    webhook = cfg.notifications.get("slack_webhook_url")
    result = cred_rotator.rotate(provider, id, slack_webhook=webhook)
    print_table("Rotacao de credencial", [result], list(result.keys()))


@tags_app.command("scan")
def tags_scan_cmd(
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
    export_path: Optional[str] = typer.Option(None, "--export", help="Salvar relatorio em .csv ou .json"),
):
    """Varre recursos sem as tags obrigatorias (definidas em config.yaml -> tagging.required_tags)."""
    provider, cfg = _get_provider(profile)
    required = cfg.tagging.get("required_tags", ["owner", "environment"])
    rows = tag_enforcer.scan(provider, required)
    print_table(
        "Recursos sem tags obrigatorias (" + ", ".join(required) + ")",
        rows,
        ["tipo", "id", "nome", "regiao", "tags_faltando"],
    )
    if export_path:
        export(rows, export_path)


@tags_app.command("fix")
def tags_fix_cmd(
    resource_id: str = typer.Option(..., help="ID do recurso a corrigir"),
    tags: str = typer.Option(..., help="Lista chave=valor separada por virgula, ex.: owner=max,environment=prod"),
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
):
    """Aplica tags a um recurso especifico."""
    provider, _ = _get_provider(profile)
    tag_dict = dict(pair.split("=", 1) for pair in tags.split(",") if "=" in pair)
    result = tag_enforcer.fix(provider, resource_id, tag_dict)
    print_table("Tags aplicadas", [result], list(result.keys()))


@app.command("tfstate-audit")
def tfstate_audit_cmd(
    state: str = typer.Option(..., help="Caminho do arquivo .tfstate"),
    profile: Optional[str] = typer.Option(None, help="Profile definido em config.yaml"),
    export_path: Optional[str] = typer.Option(None, "--export", help="Salvar relatorio em .csv ou .json"),
):
    """Compara o Terraform state com o estado real da cloud e aponta drift."""
    provider, _ = _get_provider(profile)
    try:
        rows = tfstate_auditor.audit(provider, state)
    except FileNotFoundError as exc:
        die(str(exc))
        return
    print_table(f"Auditoria de drift ({state})", rows, ["recurso", "tipo", "id", "status"])
    if export_path:
        export(rows, export_path)


@app.command("menu")
def menu_cmd():
    """Menu interativo - util para quem nao quer decorar os subcomandos."""
    cfg = load_config()
    if not cfg.profiles:
        console.print(f"[yellow]Nenhum profile configurado ainda. Edite {cfg.raw_path} e rode de novo.[/yellow]")
        raise typer.Exit(1)

    console.print("[bold cyan]cloudops-cli - menu interativo[/bold cyan]\n")
    profile_name = Prompt.ask("Profile", choices=list(cfg.profiles.keys()), default=cfg.defaults.get("profile"))

    def opt_idle_audit():
        idle_audit_cmd(profile=profile_name, export_path=None)

    def opt_creds_check():
        creds_check_cmd(profile=profile_name, max_age_days=90)

    def opt_tags_scan():
        tags_scan_cmd(profile=profile_name, export_path=None)

    options = {
        "1": ("Auditoria de recursos ociosos", opt_idle_audit),
        "2": ("Verificar credenciais a rotacionar", opt_creds_check),
        "3": ("Varrer tags obrigatorias", opt_tags_scan),
        "4": ("Ver profiles configurados", list_profiles),
    }
    for key, (label, _) in options.items():
        console.print(f"  [{key}] {label}")
    choice = Prompt.ask("Escolha uma opcao", choices=list(options.keys()))
    options[choice][1]()


@app.command("gui")
def gui_cmd():
    """Abre a interface grafica desktop (janela Tkinter) com todas as ferramentas."""
    from .gui import main as gui_main

    gui_main()


def main():
    app()


if __name__ == "__main__":
    main()
