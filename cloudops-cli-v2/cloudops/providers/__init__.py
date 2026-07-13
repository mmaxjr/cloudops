"""
Registry de providers. Para adicionar um novo provider, implemente
CloudProvider (ver base.py) e registre-o no dicionário PROVIDERS abaixo —
nenhum outro arquivo precisa mudar.
"""

from __future__ import annotations

from ..config import ProfileConfig
from .aws import AWSProvider
from .azure import AzureProvider
from .base import CloudProvider, Credential, Resource
from .gcp import GCPProvider

PROVIDERS = {
    "aws": AWSProvider,
    "gcp": GCPProvider,
    "azure": AzureProvider,
}


def build_provider(profile: ProfileConfig) -> CloudProvider:
    cls = PROVIDERS.get(profile.provider)
    if not cls:
        raise ValueError(
            f"Provider '{profile.provider}' desconhecido. Opções: {', '.join(PROVIDERS)}"
        )

    if profile.provider == "aws":
        return cls(region=profile.get("region", "us-east-1"), aws_profile=profile.get("aws_profile"))
    if profile.provider == "gcp":
        return cls(project_id=profile.get("project_id"), credentials_file=profile.get("credentials_file"))
    if profile.provider == "azure":
        return cls(subscription_id=profile.get("subscription_id"))

    raise ValueError(f"Provider '{profile.provider}' registrado mas sem regra de construção")


__all__ = ["CloudProvider", "Resource", "Credential", "PROVIDERS", "build_provider"]
