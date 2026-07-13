"""Backup cruzado: snapshot de um volume + cópia para outra região/conta/bucket."""

from __future__ import annotations

from ..providers.base import CloudProvider


def run(provider: CloudProvider, volume_id: str, destination: str) -> dict:
    snapshot_id = provider.snapshot_and_copy(volume_id, destination)
    return {
        "volume_origem": volume_id,
        "destino": destination,
        "snapshot_resultante": snapshot_id,
        "status": "concluído",
    }
