
<img width="711" height="508" alt="image" src="https://github.com/user-attachments/assets/6d0be4c8-3a96-4f7b-aeea-38ba20e3a4d3" />

# cloudops-cli

Interface única de linha de comando para 5 ferramentas de gestão de cloud
(AWS pronto para uso; GCP e Azure com a mesma interface, prontos para
completar os pontos de extensão marcados com `NotImplementedError`):

1. **idle-audit** — VMs paradas, discos sem anexo, IPs sem associação + economia potencial
2. **backup** — snapshot de um volume + cópia para outra região/conta
3. **creds check / creds rotate** — credenciais próximas do vencimento + rotação
4. **tags scan / tags fix** — recursos sem tags obrigatórias
5. **tfstate-audit** — compara um `.tfstate` com a cloud real e aponta drift

## Por que essa arquitetura facilita integrações

- Um único arquivo `~/.cloudops/config.yaml` guarda todos os "profiles"
  (conta AWS, projeto GCP, subscription Azure). Trocar de conta é só
  trocar `--profile`, nada de editar código.
- Todos os módulos (`cloudops/modules/*.py`) conversam apenas com a
  interface abstrata `CloudProvider` (`cloudops/providers/base.py`) —
  nunca com boto3/google-cloud/azure-sdk diretamente. Adicionar um
  provider novo é implementar essa interface e registrar em
  `cloudops/providers/__init__.py`; nenhum módulo muda.
- Notificações (Slack/e-mail) e exportação (CSV/JSON) são utilitários
  compartilhados, então qualquer módulo novo ganha isso de graça.

## Instalação

```bash
cd cloudops-cli
python -m venv .venv && source .venv/bin/activate   # ou .venv\Scripts\activate no Windows
pip install -e .
# ou, sem instalar como pacote:
pip install -r requirements.txt
```

Para GCP/Azure, instale os extras:
```bash
pip install -e ".[gcp]"
pip install -e ".[azure]"
```

## Configuração

Na primeira execução, o arquivo `~/.cloudops/config.yaml` é criado
automaticamente com um exemplo. Copie `config.example.yaml` por cima
dele e ajuste seus profiles reais.

## Uso

```bash
cloudops profiles

cloudops idle-audit --profile aws-prod
cloudops idle-audit --profile aws-prod --export relatorio.csv

cloudops backup --profile aws-prod --volume vol-0123456789 --to region:us-west-2

cloudops creds check --profile aws-prod
cloudops creds rotate --profile aws-prod --id AKIAABCDEFGH1234

cloudops tags scan --profile aws-prod
cloudops tags fix --profile aws-prod --resource-id i-0123456789 --tags owner=max,environment=prod

cloudops tfstate-audit --profile aws-prod --state terraform.tfstate

cloudops menu   # menu interativo, sem precisar decorar os comandos
```

## Estrutura

```
cloudops/
  cli.py                 # comandos Typer (o "menu" de tudo)
  config.py              # carrega ~/.cloudops/config.yaml
  providers/
    base.py              # interface CloudProvider (contrato único)
    aws.py                # implementação real com boto3
    gcp.py                # implementação com google-cloud (esqueleto + pontos de extensão)
    azure.py              # implementação com azure-sdk (esqueleto + pontos de extensão)
  modules/
    idle_audit.py
    backup_sync.py
    cred_rotator.py
    tag_enforcer.py
    tfstate_auditor.py
  utils/
    report.py             # tabela no terminal + export CSV/JSON
    notify.py              # Slack webhook / e-mail
```

## Status por provider

| Módulo         | AWS | GCP | Azure |
|----------------|-----|-----|-------|
| idle-audit     | ✅  | ✅  | ✅    |
| backup         | ✅  | ⏳  | ⏳    |
| creds check/rotate | ✅ | ⏳ | ⏳   |
| tags scan/fix  | ✅  | ⏳  | ⏳    |
| tfstate-audit  | ✅ (instance/volume/eip) | ⏳ | ⏳ |

⏳ = interface pronta, lógica real a implementar no ponto marcado com
`NotImplementedError` (o comentário no código já diz qual API do SDK usar).

## Interface grafica desktop

Alem da linha de comando, ha uma janela desktop nativa (Tkinter, sem
navegador e sem servidor) com uma aba para cada ferramenta e um combo de
"Profile" no topo que troca de conta AWS/GCP/Azure exatamente como no
CLI (mesmo `~/.cloudops/config.yaml`).

```bash
cloudops gui
# ou, sem passar pelo cloudops:
python -m cloudops.gui
```

Requer `tkinter` (no Linux: `sudo apt install python3-tk`; no Windows e
macOS o Tkinter ja vem com o Python padrao). Abas disponiveis: Perfis,
Auditoria de ociosos, Backup cruzado, Credenciais, Tags e Terraform
drift — cada uma com os mesmos campos dos comandos, resultado em tabela
e botoes de exportar CSV/JSON.
