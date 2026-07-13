"""Notificações opcionais (Slack webhook / e-mail) usadas pelo cred_rotator e outros módulos."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx


def notify_slack(webhook_url: Optional[str], message: str) -> None:
    if not webhook_url:
        return
    try:
        httpx.post(webhook_url, json={"text": message}, timeout=10)
    except Exception as exc:  # notificação nunca deve derrubar o comando principal
        print(f"[notify] Falha ao enviar Slack: {exc}")


def notify_email(smtp_host: str, to_addr: Optional[str], subject: str, body: str) -> None:
    if not to_addr:
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = "cloudops-cli@localhost"
        msg["To"] = to_addr
        with smtplib.SMTP(smtp_host) as server:
            server.send_message(msg)
    except Exception as exc:
        print(f"[notify] Falha ao enviar e-mail: {exc}")
