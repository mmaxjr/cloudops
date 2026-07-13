"""Lê um .tfstate e aponta drift: recursos que existem no state mas não na cloud (ou vice-versa)."""

from __future__ import annotations

import json
from pathlib import Path

from ..providers.base import CloudProvider

# Mapeia o "type" do Terraform para o kind normalizado do provider, quando aplicável.
_RESOURCE_TYPE_HINT = {
    "aws_instance": "aws_instance",
    "aws_ebs_volume": "aws_ebs_volume",
    "aws_eip": "aws_eip",
}


def _iter_state_resources(state: dict):
    for resource in state.get("resources", []):
        rtype = resource.get("type")
        for instance in resource.get("instances", []):
            attrs = instance.get("attributes", {})
            resource_id = attrs.get("id")
            if resource_id:
                yield rtype, resource_id, resource.get("name")


def audit(provider: CloudProvider, tfstate_path: str) -> list[dict]:
    path = Path(tfstate_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de state não encontrado: {tfstate_path}")

    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)

    rows = []
    for rtype, resource_id, name in _iter_state_resources(state):
        mapped_type = _RESOURCE_TYPE_HINT.get(rtype)
        if not mapped_type:
            rows.append(
                {
                    "recurso": name,
                    "tipo": rtype,
                    "id": resource_id,
                    "status": "tipo_nao_suportado_pelo_auditor",
                }
            )
            continue
        try:
            exists = provider.resource_exists(mapped_type, resource_id)
        except NotImplementedError as exc:
            rows.append({"recurso": name, "tipo": rtype, "id": resource_id, "status": f"nao_verificavel: {exc}"})
            continue

        rows.append(
            {
                "recurso": name,
                "tipo": rtype,
                "id": resource_id,
                "status": "ok" if exists else "DRIFT: existe no state mas não na cloud",
            }
        )
    return rows
