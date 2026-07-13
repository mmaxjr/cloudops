"""
Implementação Azure da interface CloudProvider.

Requer: pip install azure-identity azure-mgmt-compute azure-mgmt-network
"""

from __future__ import annotations

from .base import CloudProvider, Credential, Resource


class AzureProvider(CloudProvider):
    name = "azure"

    def __init__(self, subscription_id: str):
        self.subscription_id = subscription_id
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore
            from azure.mgmt.compute import ComputeManagementClient  # type: ignore
            from azure.mgmt.network import NetworkManagementClient  # type: ignore

            credential = DefaultAzureCredential()
            self.compute = ComputeManagementClient(credential, subscription_id)
            self.network = NetworkManagementClient(credential, subscription_id)
        except ImportError as exc:  # pragma: no cover - guia de instalação
            raise ImportError(
                "Dependências do Azure não instaladas. Rode: "
                "pip install azure-identity azure-mgmt-compute azure-mgmt-network"
            ) from exc

    def list_compute_instances(self) -> list[Resource]:
        resources = []
        for vm in self.compute.virtual_machines.list_all():
            instance_view = None
            try:
                rg = vm.id.split("/")[4]
                instance_view = self.compute.virtual_machines.instance_view(rg, vm.name)
            except Exception:
                pass
            state = "unknown"
            if instance_view:
                for status in instance_view.statuses:
                    if status.code.startswith("PowerState/"):
                        state = status.code.split("/")[-1]
            resources.append(
                Resource(
                    id=vm.id,
                    kind="vm",
                    name=vm.name,
                    region=vm.location,
                    state=state,
                    tags=dict(vm.tags or {}),
                    raw=vm,
                )
            )
        return resources

    def list_unattached_disks(self) -> list[Resource]:
        resources = []
        for disk in self.compute.disks.list():
            if disk.disk_state == "Unattached":
                resources.append(
                    Resource(
                        id=disk.id,
                        kind="disk",
                        name=disk.name,
                        region=disk.location,
                        state="unattached",
                        tags=dict(disk.tags or {}),
                        monthly_cost_estimate=round((disk.disk_size_gb or 0) * 0.045, 2),
                        raw=disk,
                    )
                )
        return resources

    def list_unassociated_ips(self) -> list[Resource]:
        resources = []
        for ip in self.network.public_ip_addresses.list_all():
            if not ip.ip_configuration:
                resources.append(
                    Resource(
                        id=ip.id,
                        kind="public_ip",
                        name=ip.name,
                        region=ip.location,
                        state="unassociated",
                        tags=dict(ip.tags or {}),
                        monthly_cost_estimate=3.65,
                        raw=ip,
                    )
                )
        return resources

    def list_credentials(self) -> list[Credential]:
        raise NotImplementedError(
            "Ponto de extensão: usar azure-mgmt-authorization / Microsoft Graph SDK "
            "para listar client secrets de service principals / app registrations."
        )

    def rotate_credential(self, credential_id: str) -> Credential:
        raise NotImplementedError(
            "Ponto de extensão: Microsoft Graph SDK -> "
            "applications.add_password(...) + remove_password(...) para o secret antigo."
        )

    def list_all_taggable_resources(self) -> list[Resource]:
        return self.list_compute_instances() + self.list_unattached_disks() + self.list_unassociated_ips()

    def apply_tags(self, resource_id: str, tags: dict[str, str]) -> None:
        raise NotImplementedError(
            "Ponto de extensão: usar azure-mgmt-resource ResourceManagementClient().tags.create_or_update_at_scope(...)"
        )

    def resource_exists(self, resource_type: str, resource_id: str) -> bool:
        raise NotImplementedError("Auditor de state para Azure: mapear resource_type do Terraform -> Azure SDK.")

    def snapshot_and_copy(self, volume_id: str, destination: str) -> str:
        raise NotImplementedError(
            "Ponto de extensão: ComputeManagementClient().snapshots.begin_create_or_update(...) "
            "e copiar para outra região/subscription conforme 'destination'."
        )
