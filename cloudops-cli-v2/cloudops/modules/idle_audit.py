"""Auditoria de recursos ociosos: VMs paradas, discos sem anexo, IPs sem associação."""

from __future__ import annotations

from ..providers.base import CloudProvider


def run(provider: CloudProvider) -> list[dict]:
    rows: list[dict] = []

    for vm in provider.list_compute_instances():
        if vm.state in ("stopped", "deallocated", "terminated"):
            rows.append(
                {
                    "tipo": "vm",
                    "id": vm.id,
                    "nome": vm.name,
                    "regiao": vm.region,
                    "estado": vm.state,
                    "custo_mensal_estimado": vm.monthly_cost_estimate or "-",
                }
            )

    for disk in provider.list_unattached_disks():
        rows.append(
            {
                "tipo": "disco",
                "id": disk.id,
                "nome": disk.name,
                "regiao": disk.region,
                "estado": disk.state,
                "custo_mensal_estimado": disk.monthly_cost_estimate or "-",
            }
        )

    for ip in provider.list_unassociated_ips():
        rows.append(
            {
                "tipo": "ip_publico",
                "id": ip.id,
                "nome": ip.name,
                "regiao": ip.region,
                "estado": ip.state,
                "custo_mensal_estimado": ip.monthly_cost_estimate or "-",
            }
        )

    return rows


def total_potential_savings(rows: list[dict]) -> float:
    total = 0.0
    for r in rows:
        cost = r.get("custo_mensal_estimado")
        if isinstance(cost, (int, float)):
            total += cost
    return round(total, 2)
