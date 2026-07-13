"""
Carrega configuração e perfis de credenciais para AWS / GCP / Azure.

A ideia central: um único arquivo YAML (~/.cloudops/config.yaml) descreve
todos os "profiles" que a ferramenta pode usar, cada um apontando para
um provider. Isso centraliza a integração: para trocar de conta/projeto/
subscription, o usuário só edita este arquivo (ou usa variáveis de
ambiente), sem precisar mexer no código dos módulos.

Exemplo de config.yaml:

profiles:
  aws-prod:
    provider: aws
    region: us-east-1
    aws_profile: prod          # nome do profile no ~/.aws/credentials
  aws-dev:
    provider: aws
    region: sa-east-1
    aws_profile: dev
  gcp-main:
    provider: gcp
    project_id: meu-projeto
    credentials_file: /caminho/service-account.json
  azure-main:
    provider: azure
    subscription_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

notifications:
  slack_webhook_url: https://hooks.slack.com/services/...
  email_to: ops@empresa.com

tagging:
  required_tags: [owner, environment, cost-center]

defaults:
  profile: aws-prod
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("CLOUDOPS_CONFIG", "~/.cloudops/config.yaml")).expanduser()


@dataclass
class ProfileConfig:
    name: str
    provider: str
    options: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


@dataclass
class AppConfig:
    profiles: dict[str, ProfileConfig]
    notifications: dict[str, Any]
    tagging: dict[str, Any]
    defaults: dict[str, Any]
    raw_path: Path

    def get_profile(self, name: Optional[str] = None) -> ProfileConfig:
        profile_name = name or self.defaults.get("profile")
        if not profile_name:
            raise ValueError(
                "Nenhum profile informado e nenhum 'defaults.profile' configurado em "
                f"{self.raw_path}"
            )
        if profile_name not in self.profiles:
            raise KeyError(
                f"Profile '{profile_name}' não encontrado em {self.raw_path}. "
                f"Disponíveis: {', '.join(self.profiles) or '(nenhum)'}"
            )
        return self.profiles[profile_name]


def _example_config() -> dict:
    return {
        "profiles": {
            "aws-default": {
                "provider": "aws",
                "region": "us-east-1",
                "aws_profile": "default",
            }
        },
        "notifications": {"slack_webhook_url": "", "email_to": ""},
        "tagging": {"required_tags": ["owner", "environment", "cost-center"]},
        "defaults": {"profile": "aws-default"},
    }


def ensure_config_exists(path: Path = DEFAULT_CONFIG_PATH) -> Path:
    """Cria um config.yaml de exemplo caso não exista, e retorna o caminho."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(_example_config(), f, sort_keys=False, allow_unicode=True)
    return path


def load_config(path: Optional[Path] = None) -> AppConfig:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        ensure_config_exists(cfg_path)

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    profiles = {
        name: ProfileConfig(name=name, provider=data["provider"], options=data)
        for name, data in (raw.get("profiles") or {}).items()
    }

    return AppConfig(
        profiles=profiles,
        notifications=raw.get("notifications") or {},
        tagging=raw.get("tagging") or {},
        defaults=raw.get("defaults") or {},
        raw_path=cfg_path,
    )
