"""
Interface grafica desktop (Tkinter) para o cloudops-cli.

Nao depende de navegador nem de servidor web: e uma janela nativa, roda
local, e reusa exatamente a mesma logica de negocio dos comandos de linha
de comando (cloudops/modules/*.py e cloudops/providers/*.py). A troca de
conta AWS/GCP/Azure continua sendo feita pelo combo de "Profile" no topo,
que le os mesmos profiles do ~/.cloudops/config.yaml.

Rodar com:
    cloudops gui
ou
    python -m cloudops.gui
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Optional

from .config import AppConfig, load_config
from .modules import backup_sync, cred_rotator, idle_audit, tag_enforcer, tfstate_auditor
from .providers import build_provider
from .utils.report import export as export_rows


def parse_tags(tags_str: str) -> dict[str, str]:
    """'owner=max,environment=prod' -> {'owner': 'max', 'environment': 'prod'}"""
    return dict(pair.split("=", 1) for pair in tags_str.split(",") if "=" in pair)


def rows_to_values(rows: list[dict], columns: list[str]) -> list[tuple]:
    """Converte uma lista de dicts em tuplas na ordem das colunas, para popular um Treeview."""
    return [tuple(str(r.get(c, "")) for c in columns) for r in rows]


class ResultTable(ttk.Frame):
    """Um Treeview + botao de exportar, reutilizado em varias abas."""

    def __init__(self, master, columns: list[str]):
        super().__init__(master)
        self.columns = columns
        self.rows: list[dict] = []

        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=12)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="w")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(btn_frame, text="Exportar CSV...", command=lambda: self._export("csv")).pack(side="left")
        ttk.Button(btn_frame, text="Exportar JSON...", command=lambda: self._export("json")).pack(
            side="left", padx=(6, 0)
        )

    def set_rows(self, rows: list[dict]) -> None:
        self.rows = rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        for values in rows_to_values(rows, self.columns):
            self.tree.insert("", "end", values=values)

    def _export(self, fmt: str) -> None:
        if not self.rows:
            messagebox.showinfo("Exportar", "Nada para exportar ainda. Rode a acao primeiro.")
            return
        ext = ".csv" if fmt == "csv" else ".json"
        path = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[(fmt.upper(), f"*{ext}")])
        if not path:
            return
        export_rows(self.rows, path)
        messagebox.showinfo("Exportar", f"Relatorio salvo em:\n{path}")


class CloudOpsGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("cloudops-cli")
        self.geometry("1000x650")

        self.cfg: AppConfig = load_config()
        self.profile_var = tk.StringVar()

        self._build_topbar()
        self._build_tabs()
        self._refresh_profiles()

    # ---------- infraestrutura comum ----------

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, padding=8)
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text="Profile:").pack(side="left")
        self.profile_combo = ttk.Combobox(bar, textvariable=self.profile_var, state="readonly", width=30)
        self.profile_combo.pack(side="left", padx=(4, 8))

        ttk.Button(bar, text="Recarregar config", command=self._refresh_profiles).pack(side="left")

        self.status_var = tk.StringVar(value="Pronto.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#555").pack(side="right")

    def _refresh_profiles(self) -> None:
        self.cfg = load_config()
        names = list(self.cfg.profiles.keys())
        self.profile_combo["values"] = names
        default = self.cfg.defaults.get("profile")
        if default in names:
            self.profile_var.set(default)
        elif names:
            self.profile_var.set(names[0])
        self._reload_profiles_tab()
        self.status_var.set(f"Config: {self.cfg.raw_path}")

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_profiles = ttk.Frame(self.notebook)
        self.tab_idle = ttk.Frame(self.notebook)
        self.tab_backup = ttk.Frame(self.notebook)
        self.tab_creds = ttk.Frame(self.notebook)
        self.tab_tags = ttk.Frame(self.notebook)
        self.tab_tfstate = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_profiles, text="Perfis")
        self.notebook.add(self.tab_idle, text="Auditoria de ociosos")
        self.notebook.add(self.tab_backup, text="Backup cruzado")
        self.notebook.add(self.tab_creds, text="Credenciais")
        self.notebook.add(self.tab_tags, text="Tags")
        self.notebook.add(self.tab_tfstate, text="Terraform drift")

        self._build_profiles_tab()
        self._build_idle_tab()
        self._build_backup_tab()
        self._build_creds_tab()
        self._build_tags_tab()
        self._build_tfstate_tab()

    def _current_provider(self):
        """Resolve o provider do profile selecionado. Levanta exception se falhar (autenticacao etc)."""
        profile = self.cfg.get_profile(self.profile_var.get())
        return build_provider(profile)

    def _run_async(self, work: Callable[[], Any], on_done: Callable[[Optional[Any], Optional[Exception]], None]) -> None:
        """Roda 'work' em thread separada para nao travar a janela, e chama 'on_done(result, error)' na thread principal."""

        def target():
            try:
                result = work()
                self.after(0, lambda: on_done(result, None))
            except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer erro de API/rede aqui
                self.after(0, lambda: on_done(None, exc))

        threading.Thread(target=target, daemon=True).start()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.status_var.set(message or ("Trabalhando..." if busy else "Pronto."))
        self.config(cursor="watch" if busy else "")

    # ---------- aba: Perfis ----------

    def _build_profiles_tab(self) -> None:
        frame = self.tab_profiles
        self.profiles_table = ResultTable(frame, columns=["profile", "provider", "detalhes"])
        self.profiles_table.pack(fill="both", expand=True, padx=8, pady=8)

    def _reload_profiles_tab(self) -> None:
        rows = [
            {
                "profile": name,
                "provider": p.provider,
                "detalhes": ", ".join(f"{k}={v}" for k, v in p.options.items() if k != "provider"),
            }
            for name, p in self.cfg.profiles.items()
        ]
        self.profiles_table.set_rows(rows)

    # ---------- aba: Auditoria de ociosos ----------

    def _build_idle_tab(self) -> None:
        frame = self.tab_idle
        top = ttk.Frame(frame, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Rodar auditoria", command=self._run_idle_audit).pack(side="left")
        self.idle_savings_var = tk.StringVar(value="Economia potencial estimada: -")
        ttk.Label(top, textvariable=self.idle_savings_var).pack(side="left", padx=(12, 0))

        self.idle_table = ResultTable(
            frame, columns=["tipo", "id", "nome", "regiao", "estado", "custo_mensal_estimado"]
        )
        self.idle_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _run_idle_audit(self) -> None:
        self._set_busy(True, "Auditando recursos ociosos...")

        def work():
            provider = self._current_provider()
            return idle_audit.run(provider)

        def done(rows, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Auditoria de ociosos", str(error))
                return
            self.idle_table.set_rows(rows)
            total = idle_audit.total_potential_savings(rows)
            self.idle_savings_var.set(f"Economia potencial estimada: US$ {total}/mes")

        self._run_async(work, done)

    # ---------- aba: Backup cruzado ----------

    def _build_backup_tab(self) -> None:
        frame = ttk.Frame(self.tab_backup, padding=8)
        frame.pack(fill="x")

        ttk.Label(frame, text="ID do volume/disco:").grid(row=0, column=0, sticky="w")
        self.backup_volume_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.backup_volume_var, width=40).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(frame, text="Destino (ex.: region:us-west-2):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.backup_dest_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.backup_dest_var, width=40).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0)
        )

        ttk.Button(frame, text="Executar backup", command=self._run_backup).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )

        self.backup_result_var = tk.StringVar(value="")
        ttk.Label(self.tab_backup, textvariable=self.backup_result_var, padding=8, foreground="#555").pack(
            anchor="w"
        )

    def _run_backup(self) -> None:
        volume = self.backup_volume_var.get().strip()
        dest = self.backup_dest_var.get().strip()
        if not volume or not dest:
            messagebox.showwarning("Backup cruzado", "Preencha o ID do volume e o destino.")
            return

        self._set_busy(True, "Criando snapshot e copiando...")

        def work():
            provider = self._current_provider()
            return backup_sync.run(provider, volume, dest)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Backup cruzado", str(error))
                return
            self.backup_result_var.set(
                f"Snapshot resultante: {result['snapshot_resultante']}  |  status: {result['status']}"
            )

        self._run_async(work, done)

    # ---------- aba: Credenciais ----------

    def _build_creds_tab(self) -> None:
        frame = self.tab_creds
        top = ttk.Frame(frame, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Idade maxima (dias):").pack(side="left")
        self.creds_max_age_var = tk.StringVar(value="90")
        ttk.Entry(top, textvariable=self.creds_max_age_var, width=6).pack(side="left", padx=(4, 12))
        ttk.Button(top, text="Verificar credenciais", command=self._run_creds_check).pack(side="left")

        ttk.Label(top, text="   ID para rotacionar:").pack(side="left", padx=(20, 0))
        self.creds_rotate_id_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.creds_rotate_id_var, width=25).pack(side="left", padx=(4, 6))
        ttk.Button(top, text="Rotacionar", command=self._run_creds_rotate).pack(side="left")

        self.creds_table = ResultTable(
            frame, columns=["id", "tipo", "dono", "idade_dias", "expira_em_dias", "status"]
        )
        self.creds_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _run_creds_check(self) -> None:
        try:
            max_age = int(self.creds_max_age_var.get())
        except ValueError:
            messagebox.showwarning("Credenciais", "Idade maxima precisa ser um numero.")
            return

        self._set_busy(True, "Verificando credenciais...")

        def work():
            provider = self._current_provider()
            return cred_rotator.check_expiring(provider, max_age_days=max_age)

        def done(rows, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Credenciais", str(error))
                return
            self.creds_table.set_rows(rows)

        self._run_async(work, done)

    def _run_creds_rotate(self) -> None:
        cred_id = self.creds_rotate_id_var.get().strip()
        if not cred_id:
            messagebox.showwarning("Credenciais", "Informe o ID da credencial a rotacionar.")
            return
        if not messagebox.askyesno("Confirmar rotacao", f"Rotacionar a credencial '{cred_id}'?"):
            return

        self._set_busy(True, "Rotacionando credencial...")

        def work():
            provider = self._current_provider()
            webhook = self.cfg.notifications.get("slack_webhook_url")
            return cred_rotator.rotate(provider, cred_id, slack_webhook=webhook)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Credenciais", str(error))
                return
            messagebox.showinfo(
                "Credenciais",
                f"Credencial antiga: {result['credencial_antiga']}\n"
                f"Credencial nova: {result['credencial_nova']}\n"
                f"Dono: {result['dono']}",
            )

        self._run_async(work, done)

    # ---------- aba: Tags ----------

    def _build_tags_tab(self) -> None:
        frame = self.tab_tags
        top = ttk.Frame(frame, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Varrer tags obrigatorias", command=self._run_tags_scan).pack(side="left")

        fix_frame = ttk.Frame(frame, padding=(8, 0, 8, 8))
        fix_frame.pack(fill="x")
        ttk.Label(fix_frame, text="ID do recurso:").grid(row=0, column=0, sticky="w")
        self.tags_resource_id_var = tk.StringVar()
        ttk.Entry(fix_frame, textvariable=self.tags_resource_id_var, width=30).grid(row=0, column=1, padx=6)

        ttk.Label(fix_frame, text="Tags (chave=valor,chave=valor):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.tags_values_var = tk.StringVar()
        ttk.Entry(fix_frame, textvariable=self.tags_values_var, width=35).grid(row=0, column=3, padx=6)

        ttk.Button(fix_frame, text="Aplicar tags", command=self._run_tags_fix).grid(row=0, column=4, padx=(6, 0))

        self.tags_table = ResultTable(frame, columns=["tipo", "id", "nome", "regiao", "tags_faltando"])
        self.tags_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _run_tags_scan(self) -> None:
        self._set_busy(True, "Varrendo tags obrigatorias...")

        def work():
            provider = self._current_provider()
            required = self.cfg.tagging.get("required_tags", ["owner", "environment"])
            return tag_enforcer.scan(provider, required)

        def done(rows, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Tags", str(error))
                return
            self.tags_table.set_rows(rows)

        self._run_async(work, done)

    def _run_tags_fix(self) -> None:
        resource_id = self.tags_resource_id_var.get().strip()
        tags_str = self.tags_values_var.get().strip()
        if not resource_id or not tags_str:
            messagebox.showwarning("Tags", "Preencha o ID do recurso e as tags (chave=valor).")
            return
        tag_dict = parse_tags(tags_str)

        self._set_busy(True, "Aplicando tags...")

        def work():
            provider = self._current_provider()
            return tag_enforcer.fix(provider, resource_id, tag_dict)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Tags", str(error))
                return
            messagebox.showinfo("Tags", f"Tags aplicadas em {resource_id}: {result['tags_aplicadas']}")

        self._run_async(work, done)

    # ---------- aba: Terraform drift ----------

    def _build_tfstate_tab(self) -> None:
        frame = self.tab_tfstate
        top = ttk.Frame(frame, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Arquivo .tfstate:").pack(side="left")
        self.tfstate_path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.tfstate_path_var, width=50).pack(side="left", padx=6)
        ttk.Button(top, text="Procurar...", command=self._browse_tfstate).pack(side="left")
        ttk.Button(top, text="Auditar drift", command=self._run_tfstate_audit).pack(side="left", padx=(12, 0))

        self.tfstate_table = ResultTable(frame, columns=["recurso", "tipo", "id", "status"])
        self.tfstate_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _browse_tfstate(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Terraform state", "*.tfstate"), ("Todos", "*.*")])
        if path:
            self.tfstate_path_var.set(path)

    def _run_tfstate_audit(self) -> None:
        path = self.tfstate_path_var.get().strip()
        if not path:
            messagebox.showwarning("Terraform drift", "Selecione um arquivo .tfstate.")
            return

        self._set_busy(True, "Auditando drift...")

        def work():
            provider = self._current_provider()
            return tfstate_auditor.audit(provider, path)

        def done(rows, error):
            self._set_busy(False)
            if error is not None:
                messagebox.showerror("Terraform drift", str(error))
                return
            self.tfstate_table.set_rows(rows)

        self._run_async(work, done)


def main() -> None:
    app = CloudOpsGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
