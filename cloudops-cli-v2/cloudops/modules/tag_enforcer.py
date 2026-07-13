"""Varre recursos sem as tags obrigatórias e opcionalmente corrige."""

from __future__ import annotations

from ..providers.base import CloudProvider


def scan(provider: CloudProvider, required_tags: list[str]) -> list[dict]:
    rows = []
    for res in provider.list_all_taggable_resources():
        missing = [t for t in required_tags if t not in res.tags]
        if missing:
            rows.append(
                {
                    "tipo": res.kind,
                    "id": res.id,
                    "nome": res.name,
                    "regiao": res.region,
                    "tags_faltando": ", ".join(missing),
                }
            )
    return rows


def fix(provider: CloudProvider, resource_id: str, tags_to_apply: dict[str, str]) -> dict:
    provider.apply_tags(resource_id, tags_to_apply)
    return {"id": resource_id, "tags_aplicadas": tags_to_apply, "status": "corrigido"}
