"""
Implementação real (boto3) da interface CloudProvider para AWS.

Cobre EC2 (instâncias, EBS, Elastic IPs), IAM (access keys) e S3
(destino de snapshot/backup cruzado).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from .base import CloudProvider, Credential, Resource


class AWSProvider(CloudProvider):
    name = "aws"

    def __init__(self, region: str, aws_profile: Optional[str] = None):
        self.region = region
        session_kwargs: dict[str, Any] = {"region_name": region}
        if aws_profile:
            session_kwargs["profile_name"] = aws_profile
        self.session = boto3.Session(**session_kwargs)
        self.ec2 = self.session.client("ec2")
        self.iam = self.session.client("iam")
        self.s3 = self.session.client("s3")

    # ---------- Idle audit ----------

    def list_compute_instances(self) -> list[Resource]:
        resources: list[Resource] = []
        paginator = self.ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                    resources.append(
                        Resource(
                            id=inst["InstanceId"],
                            kind="vm",
                            name=tags.get("Name", inst["InstanceId"]),
                            region=self.region,
                            state=inst["State"]["Name"],
                            tags=tags,
                            created_at=inst.get("LaunchTime"),
                            raw=inst,
                        )
                    )
        return resources

    def list_unattached_disks(self) -> list[Resource]:
        resources = []
        paginator = self.ec2.get_paginator("describe_volumes")
        for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
            for vol in page["Volumes"]:
                tags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
                gb = vol["Size"]
                # Estimativa simples (gp3 ~ US$0.08/GB-mês); ajuste conforme sua região/tipo.
                cost = round(gb * 0.08, 2)
                resources.append(
                    Resource(
                        id=vol["VolumeId"],
                        kind="disk",
                        name=tags.get("Name", vol["VolumeId"]),
                        region=self.region,
                        state="unattached",
                        tags=tags,
                        monthly_cost_estimate=cost,
                        created_at=vol.get("CreateTime"),
                        raw=vol,
                    )
                )
        return resources

    def list_unassociated_ips(self) -> list[Resource]:
        resources = []
        addresses = self.ec2.describe_addresses()["Addresses"]
        for addr in addresses:
            if "AssociationId" not in addr:
                tags = {t["Key"]: t["Value"] for t in addr.get("Tags", [])}
                resources.append(
                    Resource(
                        id=addr.get("AllocationId", addr["PublicIp"]),
                        kind="public_ip",
                        name=addr["PublicIp"],
                        region=self.region,
                        state="unassociated",
                        tags=tags,
                        monthly_cost_estimate=3.60,  # AWS cobra ~US$0.005/h por EIP ocioso
                        raw=addr,
                    )
                )
        return resources

    # ---------- Credential rotation ----------

    def list_credentials(self) -> list[Credential]:
        creds = []
        users = self.iam.list_users()["Users"]
        for user in users:
            keys = self.iam.list_access_keys(UserName=user["UserName"])["AccessKeyMetadata"]
            for k in keys:
                creds.append(
                    Credential(
                        id=k["AccessKeyId"],
                        kind="access_key",
                        owner=user["UserName"],
                        created_at=k.get("CreateDate"),
                        expires_at=None,  # IAM access keys não expiram nativamente; ver módulo cred_rotator
                        raw=k,
                    )
                )
        return creds

    def rotate_credential(self, credential_id: str) -> Credential:
        # Descobre o dono da key
        owner = None
        for cred in self.list_credentials():
            if cred.id == credential_id:
                owner = cred.owner
                break
        if not owner:
            raise ValueError(f"Access key {credential_id} não encontrada")

        new_key = self.iam.create_access_key(UserName=owner)["AccessKey"]
        self.iam.update_access_key(UserName=owner, AccessKeyId=credential_id, Status="Inactive")

        return Credential(
            id=new_key["AccessKeyId"],
            kind="access_key",
            owner=owner,
            created_at=new_key["CreateDate"],
            expires_at=None,
            raw=new_key,
        )

    # ---------- Tagging enforcement ----------

    def list_all_taggable_resources(self) -> list[Resource]:
        resources = self.list_compute_instances() + self.list_unattached_disks() + self.list_unassociated_ips()
        return resources

    def apply_tags(self, resource_id: str, tags: dict[str, str]) -> None:
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        self.ec2.create_tags(Resources=[resource_id], Tags=tag_list)

    # ---------- Terraform state auditor ----------

    def resource_exists(self, resource_type: str, resource_id: str) -> bool:
        checks = {
            "aws_instance": lambda rid: self._describe_ok(self.ec2.describe_instances, InstanceIds=[rid]),
            "aws_ebs_volume": lambda rid: self._describe_ok(self.ec2.describe_volumes, VolumeIds=[rid]),
            "aws_eip": lambda rid: self._describe_ok(self.ec2.describe_addresses, AllocationIds=[rid]),
        }
        check = checks.get(resource_type)
        if not check:
            raise NotImplementedError(f"Tipo de recurso '{resource_type}' ainda não suportado no auditor AWS")
        return check(resource_id)

    @staticmethod
    def _describe_ok(fn, **kwargs) -> bool:
        try:
            fn(**kwargs)
            return True
        except Exception:
            return False

    # ---------- Backup cruzado ----------

    def snapshot_and_copy(self, volume_id: str, destination: str) -> str:
        """destination no formato 'region:us-west-2' ou 's3:nome-do-bucket'."""
        snap = self.ec2.create_snapshot(VolumeId=volume_id, Description="cloudops-cli backup")
        snapshot_id = snap["SnapshotId"]

        waiter = self.ec2.get_waiter("snapshot_completed")
        waiter.wait(SnapshotIds=[snapshot_id])

        if destination.startswith("region:"):
            dest_region = destination.split(":", 1)[1]
            dest_ec2 = self.session.client("ec2", region_name=dest_region)
            copied = dest_ec2.copy_snapshot(
                SourceRegion=self.region,
                SourceSnapshotId=snapshot_id,
                Description=f"cloudops-cli cross-region backup de {volume_id}",
            )
            return copied["SnapshotId"]

        if destination.startswith("s3:"):
            # Nota: exportar snapshot EBS para S3 exige o serviço "EBS direct APIs"
            # ou o VM Import/Export; aqui deixamos o ponto de extensão claro.
            raise NotImplementedError(
                "Exportar snapshot para S3 requer EBS direct APIs — implemente aqui conforme sua necessidade."
            )

        raise ValueError(f"Destino de backup não reconhecido: {destination}")
