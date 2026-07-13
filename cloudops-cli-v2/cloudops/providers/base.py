"""
Interface comum que todo provider (AWS, GCP, Azure) precisa implementar.

Esse é o ponto central de "facilitar integrações": os módulos (idle_audit,
backup_sync, cred_rotator, tag_enforcer, tfstate_auditor) nunca chamam
boto3 / google-cloud / azure-sdk diretamente. Eles só conversam com estes
métodos abstratos. Para adicionar um provider novo, basta criar uma classe
que implemente CloudProvider e registrá-la em providers/__init__.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Resource:
    """Representação normalizada de um recurso de cloud, independente do provider."""

    id: str
    kind: str  # "vm", "disk", "public_ip", "key", etc.
    name: str
    region: str
    state: str  # "running", "stopped", "unattached", "unassociated", ...
    tags: dict[str, str] = field(default_factory=dict)
    monthly_cost_estimate: Optional[float] = None
    created_at: Optional[datetime] = None
    raw: Any = None  # objeto original do SDK, se precisar de detalhe extra


@dataclass
class Credential:
    id: str
    kind: str  # "access_key", "service_account_key", "client_secret", ...
    owner: str
    created_at: Optional[datetime]
    expires_at: Optional[datetime]
    raw: Any = None


class CloudProvider(ABC):
    """Contrato que cada provider concreto deve cumprir."""

    name: str = "base"

    @abstractmethod
    def list_compute_instances(self) -> list[Resource]:
        """Lista VMs/instâncias (rodando ou paradas)."""

    @abstractmethod
    def list_unattached_disks(self) -> list[Resource]:
        """Discos/volumes sem nenhuma instância associada."""

    @abstractmethod
    def list_unassociated_ips(self) -> list[Resource]:
        """IPs públicos/elásticos reservados mas não associados a nada."""

    @abstractmethod
    def list_credentials(self) -> list[Credential]:
        """Chaves/credenciais de acesso programático (para rotação)."""

    @abstractmethod
    def rotate_credential(self, credential_id: str) -> Credential:
        """Cria uma nova credencial e desativa/agenda a remoção da antiga."""

    @abstractmethod
    def list_all_taggable_resources(self) -> list[Resource]:
        """Todos os recursos relevantes para checagem de tags obrigatórias."""

    @abstractmethod
    def apply_tags(self, resource_id: str, tags: dict[str, str]) -> None:
        """Aplica/corrige tags em um recurso."""

    @abstractmethod
    def resource_exists(self, resource_type: str, resource_id: str) -> bool:
        """Usado pelo tfstate_auditor para checar se um recurso do state existe de fato na cloud."""

    @abstractmethod
    def snapshot_and_copy(self, volume_id: str, destination: str) -> str:
        """Cria snapshot de um volume/disco e copia para outra região/conta/bucket. Retorna o id do snapshot."""
