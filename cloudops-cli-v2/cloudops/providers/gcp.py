"""
Implementação GCP da interface CloudProvider.

As chamadas usam a biblioteca `google-cloud-compute` / `google-cloud-iam`.
Os métodos abaixo já resolvem autenticação e paginação; a lógica de negócio
(o que é "ocioso", como aplicar tags/labels, etc.) segue o mesmo contrato
que a AWS, então os módulos em cloudops/modules/ funcionam sem alteração.

Requer: pip install google-cloud-compute google-cloud-resource-manager
"""

from __future__ import annotations

from typing import Optional

from .base import CloudProvider, Credential, Resource


class GCPProvider(CloudProvider):
    name = "gcp"

    def __init__(self, project_id: str, credentials_file: Optional[str] = None):
        self.project_id = project_id
        self.credentials_file = credentials_file
        try:
            from google.cloud import compute_v1  # type: ignore

            self._compute_v1 = compute_v1
            if credentials_file:
                from google.oauth2 import service_account  # type: ignore

                self._credentials = service_account.Credentials.from_service_account_file(credentials_file)
            else:
                self._credentials = None
        except ImportError as exc:  # pragma: no cover - guia de instalação
            raise ImportError(
                "Dependências do GCP não instaladas. Rode: "
                "pip install google-cloud-compute google-cloud-resource-manager"
            ) from exc

    def _instances_client(self):
        return self._compute_v1.InstancesClient(credentials=self._credentials)

    def _disks_client(self):
        return self._compute_v1.DisksClient(credentials=self._credentials)

    def _addresses_client(self):
        return self._compute_v1.AddressesClient(credentials=self._credentials)

    def list_compute_instances(self) -> list[Resource]:
        client = self._instances_client()
        agg = client.aggregated_list(project=self.project_id)
        resources = []
        for zone, response in agg:
            for inst in response.instances or []:
                resources.append(
                    Resource(
                        id=str(inst.id),
                        kind="vm",
                        name=inst.name,
                        region=zone.split("/")[-1],
                        state=inst.status.lower(),
                        tags=dict(inst.labels or {}),
                        raw=inst,
                    )
                )
        return resources

    def list_unattached_disks(self) -> list[Resource]:
        client = self._disks_client()
        agg = client.aggregated_list(project=self.project_id)
        resources = []
        for zone, response in agg:
            for disk in response.disks or []:
                if not disk.users:
                    resources.append(
                        Resource(
                            id=str(disk.id),
                            kind="disk",
                            name=disk.name,
                            region=zone.split("/")[-1],
                            state="unattached",
                            tags=dict(disk.labels or {}),
                            monthly_cost_estimate=round(disk.size_gb * 0.04, 2),  # pd-standard aprox.
                            raw=disk,
                        )
                    )
        return resources

    def list_unassociated_ips(self) -> list[Resource]:
        client = self._addresses_client()
        agg = client.aggregated_list(project=self.project_id)
        resources = []
        for region, response in agg:
            for addr in response.addresses or []:
                if addr.status == "RESERVED":  # reservado mas não em uso
                    resources.append(
                        Resource(
                            id=str(addr.id),
                            kind="public_ip",
                            name=addr.address,
                            region=region.split("/")[-1],
                            state="unassociated",
                            tags=dict(addr.labels or {}),
                            monthly_cost_estimate=2.88,
                            raw=addr,
                        )
                    )
        return resources

    def list_credentials(self) -> list[Credential]:
        raise NotImplementedError(
            "Listagem de service account keys via google-cloud-iam ainda não implementada. "
            "Ponto de extensão: iam_admin_v1.IAMClient().list_service_account_keys(...)"
        )

    def rotate_credential(self, credential_id: str) -> Credential:
        raise NotImplementedError(
            "Rotação de service account key ainda não implementada. "
            "Ponto de extensão: iam_admin_v1.IAMClient().create_service_account_key(...) "
            "+ delete_service_account_key(...) para a antiga."
        )

    def list_all_taggable_resources(self) -> list[Resource]:
        return self.list_compute_instances() + self.list_unattached_disks() + self.list_unassociated_ips()

    def apply_tags(self, resource_id: str, tags: dict[str, str]) -> None:
        raise NotImplementedError(
            "GCP usa 'labels' em vez de tags. Ponto de extensão: "
            "InstancesClient().set_labels(project=..., zone=..., instance=..., "
            "instances_set_labels_request_resource=...)"
        )

    def resource_exists(self, resource_type: str, resource_id: str) -> bool:
        raise NotImplementedError("Auditor de state para GCP: mapear resource_type do Terraform -> API do GCP.")

    def snapshot_and_copy(self, volume_id: str, destination: str) -> str:
        raise NotImplementedError(
            "Ponto de extensão: DisksClient().create_snapshot(...) e depois "
            "copiar o snapshot para outra região/projeto conforme 'destination'."
        )
