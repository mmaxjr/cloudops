"""Rotação de credenciais/chaves de API, com aviso antes do vencimento."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..providers.base import CloudProvider
from ..utils.notify import notify_slack


def check_expiring(provider: CloudProvider, max_age_days: int = 90) -> list[dict]:
    """Como nem toda cloud expõe 'expires_at' nativamente (ex.: IAM access keys),
    usamos idade da credencial como proxy: mais velha que max_age_days = candidata a rotação."""
    now = datetime.now(timezone.utc)
    rows = []
    for cred in provider.list_credentials():
        age_days = None
        if cred.created_at:
            created = cred.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (now - created).days

        expires_in = None
        status = "ok"
        if cred.expires_at:
            expires_in = (cred.expires_at - now).days
            status = "expirando" if expires_in <= 15 else "ok"
        elif age_days is not None and age_days >= max_age_days:
            status = "vencida_por_idade"

        rows.append(
            {
                "id": cred.id,
                "tipo": cred.kind,
                "dono": cred.owner,
                "idade_dias": age_days,
                "expira_em_dias": expires_in,
                "status": status,
            }
        )
    return rows


def rotate(provider: CloudProvider, credential_id: str, slack_webhook: str | None = None) -> dict:
    new_cred = provider.rotate_credential(credential_id)
    message = (
        f":key: Credencial `{credential_id}` (dono: {new_cred.owner}) foi rotacionada. "
        f"Nova credencial: `{new_cred.id}`. Atualize os secrets dependentes o quanto antes."
    )
    notify_slack(slack_webhook, message)
    return {
        "credencial_antiga": credential_id,
        "credencial_nova": new_cred.id,
        "dono": new_cred.owner,
        "status": "rotacionada",
    }
