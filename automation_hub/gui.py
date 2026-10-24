from __future__ import annotations

from collections import Counter
import queue
import threading
import uuid
from pathlib import Path
from tkinter import BooleanVar, Canvas, Listbox, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from typing import Any, Callable, TypeVar

from .blogger_automation import run_link_job
from .google_blogger import GoogleBloggerConnector
from .i18n import SUPPORTED_LOCALES, tr
from .jobs import JobStore, JobStoreError
from .models import BloggerLinkJob, ScheduleSpec
from .scheduler import WindowsTaskScheduler
from .schedule_approval import ScheduleApprovalStore
from .settings import SettingsStore
from .ui_flow import home_progress, job_revision, live_run_ready, needs_save

T = TypeVar("T")


class AutomationHubGUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.settings_store = SettingsStore()
        self.job_store = JobStore()
        self.scheduler = WindowsTaskScheduler()
        self.schedule_approvals = ScheduleApprovalStore()
        self.google = GoogleBloggerConnector()
        self.settings = self.settings_store.load()
        self.locale = str(self.settings.get("locale", "ja"))
        if self.locale not in SUPPORTED_LOCALES:
            self.locale = "ja"
        self.blogs: list[dict[str, str]] = []
        self.blog_display_to_id: dict[str, str] = {}
        # UI shows readable names; IDs stay in a separate index to avoid
        # cryptic, clipped suffixes and safely handle identical job names.
        self.job_row_ids: list[str] = []
        self.selected_job_id: str | None = None
        self.selected_schedule_job_id: str | None = None
        self.busy = False
        self.preview_revision: str | None = None
        self.google_verified = False  # OAuth token presence is not a verified API connection.
        self._async_queue: queue.Queue[tuple[str, Any, Callable[[Any], None] | None]] = queue.Queue()
        self.root.geometry("940x670")
        self.root.minsize(840, 580)
        self._migrate_legacy_google_config()
        self.build_ui()
        self.root.after(100, self._poll_async_queue)

    def t(self, key: str, **kwargs: object) -> str:
        return tr(self.locale, key, **kwargs)

    def _migrate_legacy_google_config(self) -> None:
        legacy = str(self.settings.pop("_legacy_google_credentials_file", "") or "").strip()
        if not legacy or self.google.has_client_config():
            return
        try:
            source = Path(legacy)
            if source.is_file():
                result = self.google.import_client_config(source)
                self.settings["google_client_id_hint"] = result.metadata.client_id_hint
                self.settings["google_project_id"] = result.metadata.project_id
                self.settings_store.save(self.settings)
        except Exception:
            # Legacy migration must never prevent the GUI from starting.
            pass

    def build_ui(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(self.t("app_title"))
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=self.t("language")).pack(side="left")
        self.language_var = StringVar(value="日本語" if self.locale == "ja" else "English")
        lang = ttk.Combobox(top, textvariable=self.language_var, values=["日本語", "English"], state="readonly", width=10)
        lang.pack(side="left", padx=(6, 12))
        lang.bind("<<ComboboxSelected>>", self.on_language_change)
        ttk.Label(top, text=self.t("desktop_note")).pack(side="left", padx=10)
        self.operation_status = StringVar(
            value=self.t("busy_processing") if self.busy else ""
        )
        ttk.Label(top, textvariable=self.operation_status).pack(side="right", padx=10)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.home_tab = ttk.Frame(self.notebook, padding=18)
        self.google_tab = ttk.Frame(self.notebook, padding=14)
        self.jobs_tab = ttk.Frame(self.notebook, padding=14)
        self.schedule_tab = ttk.Frame(self.notebook, padding=14)
        self.compliance_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.home_tab, text=self.t("tab_home"))
        self.notebook.add(self.google_tab, text=self.t("tab_google"))
        self.notebook.add(self.jobs_tab, text=self.t("tab_jobs"))
        self.notebook.add(self.schedule_tab, text=self.t("tab_schedule"))
        self.notebook.add(self.compliance_tab, text=self.t("tab_compliance"))
        self._build_home_tab()
        self._build_google_tab()
        self._build_jobs_tab()
        self._build_schedule_tab()
        self._build_compliance_tab()
        self.refresh_jobs(show_error=False)

    def _build_home_tab(self) -> None:
        """Explain what the product actually does before exposing advanced settings."""
        # A vertical viewport keeps real jobs and the 3 setup steps reachable
        # on a smaller Windows display or at increased text scaling.
        viewport = self.home_tab
        self.home_canvas = Canvas(viewport, highlightthickness=0, borderwidth=0)
        self.home_scrollbar = ttk.Scrollbar(
            viewport, orient="vertical", command=self.home_canvas.yview)
        self.home_canvas.configure(yscrollcommand=self.home_scrollbar.set)
        self.home_scrollbar.pack(side="right", fill="y")
        self.home_canvas.pack(side="left", fill="both", expand=True)
        frame = ttk.Frame(self.home_canvas)
        window = self.home_canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _event: self.home_canvas.configure(
            scrollregion=self.home_canvas.bbox("all")))
        self.home_canvas.bind("<Configure>", lambda event: self.home_canvas.itemconfigure(
            window, width=event.width))
        ttk.Label(
            frame, text=self.t("home_title"), font=("Segoe UI", 19, "bold")
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frame, text=self.t("home_what"), wraplength=800, justify="left"
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frame, text=self.t("home_example"), wraplength=800, justify="left",
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(0, 14))

        def step(title_key: str, desc_key: str, button_key: str, tab: ttk.Frame) -> StringVar:
            box = ttk.LabelFrame(frame, text=self.t(title_key), padding=12)
            box.pack(fill="x", pady=(0, 10))
            ttk.Label(box, text=self.t(desc_key), wraplength=730, justify="left").pack(anchor="w", pady=(0, 5))
            status = StringVar()
            ttk.Label(box, textvariable=status).pack(anchor="w", pady=(0, 8))
            ttk.Button(box, text=self.t(button_key), command=lambda target=tab: self.notebook.select(target)).pack(anchor="w")
            return status

        self.home_connection_status = step(
            "home_connect_title", "home_connect_help",
            "home_connect_action", self.google_tab
        )
        self.home_jobs_status = step(
            "home_job_title", "home_job_help",
            "home_job_action", self.jobs_tab
        )
        self.home_preview_status = step(
            "home_preview_title", "home_preview_help",
            "home_preview_action", self.jobs_tab
        )
        jobs_area = ttk.LabelFrame(
            frame,
            text="保存済みのBlogger作業" if self.locale == "ja" else "Saved Blogger jobs",
            padding=9)
        jobs_area.pack(fill="x", pady=(4, 10))
        self.home_saved_jobs = Listbox(jobs_area, height=4, exportselection=False)
        self.home_saved_jobs.pack(side="left", fill="x", expand=True)
        ttk.Button(jobs_area,
                   text="作業を開く" if self.locale == "ja" else "Open jobs",
                   command=lambda: self.notebook.select(self.jobs_tab)).pack(
                       side="right", padx=(10, 0))
        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(2, 0))
        ttk.Label(footer, text=self.t("home_schedule_help"), wraplength=620).pack(side="left")
        ttk.Button(
            footer, text=self.t("home_schedule_action"),
            command=lambda: self.notebook.select(self.schedule_tab)
        ).pack(side="right")
        self._refresh_home_status()

    def _refresh_home_status(self) -> None:
        if not hasattr(self, "home_connection_status"):
            return
        try:
            saved_jobs = self.job_store.load_all()
            count = len(saved_jobs)
        except JobStoreError:
            saved_jobs = None
            count = None
        if hasattr(self, "home_saved_jobs"):
            self.home_saved_jobs.delete(0, "end")
            if saved_jobs is None:
                self.home_saved_jobs.insert(
                    "end", "読み込み失敗" if self.locale == "ja" else "Could not load jobs")
            elif not saved_jobs:
                self.home_saved_jobs.insert(
                    "end", "まだ登録がありません" if self.locale == "ja" else "No saved jobs yet")
            else:
                for job in saved_jobs:
                    state = ("有効" if job.enabled else "停止中") if self.locale == "ja" else (
                        "Enabled" if job.enabled else "Disabled")
                    self.home_saved_jobs.insert("end", f"{job.name} — {state}")
        try:
            configured = self.google.has_client_config()
            token_present = self.google.has_token()
        except Exception:
            configured, token_present = False, False
        auth_state, job_state, _ = home_progress(configured, token_present, count)
        self.home_connection_status.set(
            self.t("home_state_api_verified") if self.google_verified
            else self.t("home_state_" + auth_state)
        )
        self.home_jobs_status.set(self.t("home_state_" + job_state, count=count if count is not None else 0))
        preview_matches = False
        if self.preview_revision and self.selected_job_id:
            try:
                preview_matches = job_revision(self.job_store.get(self.selected_job_id)) == self.preview_revision
            except (KeyError, JobStoreError, ValueError):
                preview_matches = False
        self.home_preview_status.set(
            self.t("home_state_preview_done") if preview_matches else self.t("home_state_preview_needed")
        )

    def _google_status_text(self) -> str:
        client = self.t("oauth_imported") if self.google.has_client_config() else self.t("oauth_not_imported")
        token = (
            self.t("home_state_api_verified") if self.google_verified
            else self.t("oauth_saved_unverified") if self.google.has_token()
            else self.t("status_not_connected")
        )
        return f"{self.t('oauth_config_status')}: {client}    {self.t('google_auth_status')}: {token}"

    def _client_info_text(self) -> str:
        if not self.google.has_client_config():
            return ""
        try:
            metadata = self.google.client_metadata()
            project = metadata.project_id or "-"
            return self.t("oauth_client_info", client_id=metadata.client_id_hint, project_id=project)
        except Exception as exc:
            return f"{self.t('oauth_config_invalid')}: {exc}"

    def _build_google_tab(self) -> None:
        frame = self.google_tab
        ttk.Label(frame, text=self.t("google_help"), wraplength=850, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )
        buttons = ttk.LabelFrame(frame, text=self.t("google_first_setup"), padding=10)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(buttons, text=self.t("import_oauth"), command=self.choose_credentials).grid(row=0, column=0, padx=(0, 10), pady=3, sticky="w")
        ttk.Button(buttons, text=self.t("authenticate"), command=self.authenticate_google).grid(row=0, column=1, padx=(0, 10), pady=3, sticky="w")
        ttk.Button(buttons, text=self.t("connection_test"), command=self.test_google).grid(row=0, column=2, padx=0, pady=3, sticky="w")
        ttk.Label(buttons, text=self.t("google_first_setup_tip"), wraplength=750).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(7, 0)
        )

        advanced = ttk.LabelFrame(frame, text=self.t("google_management"), padding=10)
        advanced.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(advanced, text=self.t("load_blogs"), command=self.load_blogs).pack(side="left", padx=(0, 8))
        ttk.Button(advanced, text=self.t("disconnect"), command=self.disconnect_google).pack(side="left", padx=(0, 8))
        ttk.Button(advanced, text=self.t("remove_oauth_config"), command=self.remove_google_config).pack(side="left")

        self.google_status_var = StringVar(value=self._google_status_text())
        ttk.Label(frame, textvariable=self.google_status_var, wraplength=850).grid(row=3, column=0, columnspan=2, sticky="w")
        self.client_info_var = StringVar(value=self._client_info_text())
        ttk.Label(frame, textvariable=self.client_info_var, wraplength=850).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.blog_text_var = StringVar(value="")
        ttk.Label(frame, textvariable=self.blog_text_var, wraplength=850).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_jobs_tab(self) -> None:
        outer = self.jobs_tab
        # A vertical viewport keeps the preview and action buttons reachable
        # on small screens and at high Windows text scaling.
        self.job_canvas = Canvas(outer, highlightthickness=0, borderwidth=0)
        self.job_scrollbar = ttk.Scrollbar(
            outer, orient="vertical", command=self.job_canvas.yview
        )
        self.job_canvas.configure(yscrollcommand=self.job_scrollbar.set)
        self.job_canvas.pack(side="left", fill="both", expand=True)
        self.job_scrollbar.pack(side="right", fill="y")
        inner = ttk.Frame(self.job_canvas)
        self.job_inner = inner
        window = self.job_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda _event: self.job_canvas.configure(
                scrollregion=self.job_canvas.bbox("all")
            ),
        )
        self.job_canvas.bind(
            "<Configure>",
            lambda event: self.job_canvas.itemconfigure(window, width=event.width),
        )
        left = ttk.Frame(inner)
        left.pack(side="left", fill="y", padx=(0, 10))
        right = ttk.Frame(inner)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text=self.t("jobs")).pack(anchor="w")
        list_holder = ttk.Frame(left)
        list_holder.pack(fill="y", expand=True, pady=6)
        self.jobs_list = Listbox(list_holder, width=22, height=16, exportselection=False)
        self.jobs_list.pack(side="left", fill="y", expand=True)
        list_scroll = ttk.Scrollbar(
            list_holder, orient="vertical", command=self.jobs_list.yview
        )
        list_scroll.pack(side="right", fill="y")
        self.jobs_list.configure(yscrollcommand=list_scroll.set)
        self.jobs_list.bind("<<ListboxSelect>>", self.on_job_select)
        ttk.Button(left, text=self.t("new_job"), command=self.new_job).pack(
            fill="x", pady=(4, 0)
        )

        self.job_name_var = StringVar()
        self.blog_var = StringVar()
        self.target_var = StringVar()
        self.anchor_var = StringVar()
        self.link_var = StringVar()
        self.max_posts_var = StringVar(value="50")
        self.enabled_var = BooleanVar(value=True)
        fields = [
            ("job_name", self.job_name_var), ("blog", self.blog_var), ("target_text", self.target_var),
            ("anchor_text", self.anchor_var), ("link_url", self.link_var), ("max_posts", self.max_posts_var),
        ]
        for row, (key, variable) in enumerate(fields):
            ttk.Label(right, text=self.t(key)).grid(row=row, column=0, sticky="w", pady=5)
            if key == "blog":
                self.blog_combo = ttk.Combobox(right, textvariable=variable, state="readonly", width=38)
                self.blog_combo.grid(row=row, column=1, sticky="ew", padx=8)
            else:
                ttk.Entry(right, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8)
        right.columnconfigure(1, weight=1)
        ttk.Checkbutton(right, text=self.t("enabled"), variable=self.enabled_var).grid(row=6, column=1, sticky="w", padx=8, pady=5)
        actions = ttk.LabelFrame(right, text=self.t("job_action_title"), padding=8)
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        # Separate 'save + preview' from the side-effecting live action.
        # Two rows also prevent long Japanese labels from overflowing at 150%.
        ttk.Button(actions, text=self.t("save_job"), command=self.save_job).grid(
            row=0, column=0, sticky="ew", padx=(0, 8), pady=3
        )
        ttk.Button(actions, text=self.t("run_dry"), command=lambda: self.run_job(True)).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Button(actions, text=self.t("run_now"), command=lambda: self.run_job(False)).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        ttk.Button(actions, text=self.t("delete_job"), command=self.delete_job).grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=3
        )
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Label(right, text=self.t("job_effect_title"), font=("Segoe UI", 10, "bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(7, 3)
        )
        self.job_effect_var = StringVar()
        ttk.Label(right, textvariable=self.job_effect_var, wraplength=550, justify="left").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        for variable in (self.target_var, self.anchor_var, self.link_var, self.max_posts_var):
            variable.trace_add("write", lambda *_args: self._refresh_job_effect())
        self._refresh_job_effect()

    def _refresh_job_effect(self) -> None:
        if not hasattr(self, "job_effect_var"):
            return
        target = self.target_var.get().strip()
        anchor = self.anchor_var.get().strip() or target
        url = self.link_var.get().strip()
        if not target or not url:
            self.job_effect_var.set(self.t("job_effect_missing"))
            return
        self.job_effect_var.set(self.t(
            "job_effect_template",
            target=target[:45], anchor=anchor[:45], url=url[:90],
            count=self.max_posts_var.get().strip() or "?",
        ))

    def _build_schedule_tab(self) -> None:
        frame = self.schedule_tab
        self.schedule_job_var = StringVar()
        self.schedule_kind_var = StringVar(value=self.t("daily"))
        self.schedule_time_var = StringVar(value="08:00")
        self.weekday_vars = {
            day: BooleanVar(value=day in {"MON", "TUE", "WED", "THU", "FRI"})
            for day in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        }
        ttk.Label(frame, text=self.t("jobs")).grid(row=0, column=0, sticky="w", pady=6)
        self.schedule_job_combo = ttk.Combobox(frame, textvariable=self.schedule_job_var, state="readonly", width=52)
        self.schedule_job_combo.grid(row=0, column=1, sticky="w", padx=8)
        self.schedule_job_combo.bind("<<ComboboxSelected>>", self.on_schedule_job_select)
        ttk.Label(frame, text=self.t("schedule_kind")).grid(row=1, column=0, sticky="w", pady=6)
        self.schedule_kind_combo = ttk.Combobox(
            frame, textvariable=self.schedule_kind_var, state="readonly",
            values=[self.t("daily"), self.t("weekly"), self.t("logon")], width=25,
        )
        self.schedule_kind_combo.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(frame, text=self.t("time")).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.schedule_time_var, width=10).grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(frame, text=self.t("weekdays")).grid(row=3, column=0, sticky="nw", pady=6)
        weekdays_frame = ttk.Frame(frame)
        weekdays_frame.grid(row=3, column=1, sticky="w", padx=8)
        names = [
            ("MON", "monday"), ("TUE", "tuesday"), ("WED", "wednesday"), ("THU", "thursday"),
            ("FRI", "friday"), ("SAT", "saturday"), ("SUN", "sunday"),
        ]
        for index, (day, key) in enumerate(names):
            ttk.Checkbutton(weekdays_frame, text=self.t(key), variable=self.weekday_vars[day]).grid(row=0, column=index, padx=(0, 6))
        buttons = ttk.LabelFrame(frame, text=self.t("schedule_action_title"), padding=8)
        buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 8))
        ttk.Button(buttons, text=self.t("save"), command=self.save_schedule_to_job).grid(
            row=0, column=0, sticky="ew", padx=(0, 8), pady=3
        )
        ttk.Button(buttons, text=self.t("test_scheduler"), command=self.test_scheduler).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Button(buttons, text=self.t("register_schedule"), command=self.register_schedule).grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=3
        )
        ttk.Button(buttons, text=self.t("remove_schedule"), command=self.remove_schedule).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        self.scheduler_status_var = StringVar(value="")
        ttk.Label(frame, textvariable=self.scheduler_status_var, wraplength=800).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame, text=self.t("schedule_advanced_notice"), wraplength=780, justify="left"
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _build_compliance_tab(self) -> None:
        text = "\n\n".join([
            self.t("supported_api_note"), self.t("free_setup"), self.t("review_date"), self.t("blogger_compliance"),
            self.t("scheduler_compliance"), self.t("compliance_note"),
        ])
        ttk.Label(self.compliance_tab, text=text, wraplength=850, justify="left").pack(anchor="w")

    def on_language_change(self, _event: object = None) -> None:
        if self.busy:
            self.language_var.set("日本語" if self.locale == "ja" else "English")
            self._reject_if_busy()
            return
        next_locale = "ja" if self.language_var.get() == "日本語" else "en"
        if next_locale == self.locale:
            return
        # Changing display language must never destroy in-progress job input.
        fields = {
            "job_name_var": self.job_name_var.get(),
            "blog_var": self.blog_var.get(),
            "target_var": self.target_var.get(),
            "anchor_var": self.anchor_var.get(),
            "link_var": self.link_var.get(),
            "max_posts_var": self.max_posts_var.get(),
        }
        enabled = self.enabled_var.get()
        old_kind = {
            self.t("daily"): "daily",
            self.t("weekly"): "weekly",
            self.t("logon"): "logon",
        }.get(self.schedule_kind_var.get(), "daily")
        schedule_time = self.schedule_time_var.get()
        week = {day: item.get() for day, item in self.weekday_vars.items()}
        schedule_choice = self.schedule_job_var.get()
        tab_index = self.notebook.index(self.notebook.select())
        self.locale = next_locale
        self.settings["locale"] = self.locale
        self.settings_store.save(self.settings)
        self.build_ui()
        for name, value in fields.items():
            getattr(self, name).set(value)
        self.enabled_var.set(enabled)
        self.schedule_kind_var.set(self.t(old_kind))
        self.schedule_time_var.set(schedule_time)
        for day, enabled_day in week.items():
            self.weekday_vars[day].set(enabled_day)
        self.schedule_job_var.set(schedule_choice)
        self.notebook.select(tab_index)
        if self.selected_job_id:
            self._restore_list_selection()
        self._refresh_home_status()

    def choose_credentials(self) -> None:
        if self._reject_if_busy():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title=self.t("select_credentials"),
            filetypes=[("Google OAuth JSON", "*.json"), ("JSON", "*.json")],
        )
        if not path:
            return
        try:
            result = self.google.import_client_config(Path(path))
            self.google_verified = False
            self.preview_revision = None
            self.settings["google_client_id_hint"] = result.metadata.client_id_hint
            self.settings["google_project_id"] = result.metadata.project_id
            self.settings_store.save(self.settings)
            self.google_status_var.set(self._google_status_text())
            self.client_info_var.set(self._client_info_text())
            self._refresh_home_status()
            key = "oauth_imported_token_reset" if result.token_reset else "oauth_imported_ok"
            messagebox.showinfo(self.t("info_title"), self.t(key))
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        self.root.config(cursor="watch" if value else "")
        if hasattr(self, "operation_status"):
            self.operation_status.set(self.t("busy_processing") if value else "")

    def _reject_if_busy(self) -> bool:
        if not self.busy:
            return False
        messagebox.showinfo(
            self.t("info_title"), self.t("busy_processing"), parent=self.root
        )
        return True

    def run_async(self, func: Callable[[], T], on_success: Callable[[T], None]) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                value = func()
            except Exception as exc:
                self._async_queue.put(("error", exc, None))
            else:
                self._async_queue.put(("ok", value, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_async_queue(self) -> None:
        try:
            while True:
                kind, value, callback = self._async_queue.get_nowait()
                self._set_busy(False)
                if kind == "error":
                    messagebox.showerror(self.t("error_title"), str(value))
                elif callback is not None:
                    try:
                        callback(value)
                    except Exception as exc:
                        messagebox.showerror(self.t("error_title"), str(exc))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_async_queue)

    def authenticate_google(self) -> None:
        self.google_verified = False
        self.preview_revision = None
        self._refresh_home_status()
        self.run_async(lambda: self.google.authenticate(self.locale), lambda _value: self._after_auth())

    def _after_auth(self) -> None:
        self.google_status_var.set(self._google_status_text())
        messagebox.showinfo(self.t("info_title"), self.t("auth_completed"))
        self.load_blogs()

    def test_google(self) -> None:
        self.google_verified = False
        self._refresh_home_status()
        self.run_async(self.google.check_connection, self._checked_google_result)

    def _checked_google_result(self, result: Any) -> None:
        if not result.ok:
            self.google_verified = False
            self.google_status_var.set(self._google_status_text())
            self._refresh_home_status()
            messagebox.showerror(
                self.t("error_title"), self.t("google_connection_failed"),
                parent=self.root,
            )
            return
        self._after_google_test(result.blogs)

    def _after_google_test(self, blogs: list[dict[str, str]]) -> None:
        self.google_verified = True
        self._set_blogs(blogs)
        self.google_status_var.set(self._google_status_text())
        self._refresh_home_status()
        messagebox.showinfo(self.t("info_title"), self.t("google_connected"))

    def load_blogs(self) -> None:
        self.run_async(self.google.list_blogs, self._after_blogs_loaded)

    def _after_blogs_loaded(self, blogs: list[dict[str, str]]) -> None:
        self.google_verified = True
        self._set_blogs(blogs)
        self.google_status_var.set(self._google_status_text())
        self._refresh_home_status()
        self.blog_text_var.set(self.t("blogs_loaded", count=len(blogs)))

    def _set_blogs(self, blogs: list[dict[str, str]]) -> None:
        self.blogs = blogs
        self.blog_display_to_id = {}
        displays: list[str] = []
        for blog in blogs:
            display = f"{blog.get('name', '')} — {blog.get('url', '')}".strip(" —") or blog.get("id", "")
            displays.append(display)
            self.blog_display_to_id[display] = blog.get("id", "")
        if hasattr(self, "blog_combo"):
            self.blog_combo["values"] = displays
            current = self.blog_var.get().strip()
            if current and current not in self.blog_display_to_id:
                mapped = next(
                    (label for label, ident in self.blog_display_to_id.items() if ident == current),
                    None,
                )
                if mapped:
                    self.blog_var.set(mapped)

    def disconnect_google(self) -> None:
        if self._reject_if_busy():
            return
        if not messagebox.askyesno(self.t("warning_title"), self.t("confirm_disconnect")):
            return
        try:
            self.google.disconnect()
            self.google_verified = False
            self.preview_revision = None
            self.google_status_var.set(self._google_status_text())
            self._refresh_home_status()
            messagebox.showinfo(self.t("info_title"), self.t("google_disconnected"))
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))

    def remove_google_config(self) -> None:
        if self._reject_if_busy():
            return
        if not messagebox.askyesno(self.t("warning_title"), self.t("confirm_remove_oauth")):
            return
        try:
            self.google.remove_client_config()
            self.google_verified = False
            self.preview_revision = None
            self.settings["google_client_id_hint"] = ""
            self.settings["google_project_id"] = ""
            self.settings_store.save(self.settings)
            self.google_status_var.set(self._google_status_text())
            self.client_info_var.set("")
            self._refresh_home_status()
            self.blogs = []
            self.blog_display_to_id = {}
            if hasattr(self, "blog_combo"):
                self.blog_combo["values"] = []
            messagebox.showinfo(self.t("info_title"), self.t("oauth_removed"))
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))

    def refresh_jobs(self, *, show_error: bool = True) -> None:
        try:
            jobs = self.job_store.load_all()
        except JobStoreError as exc:
            if hasattr(self, "jobs_list"):
                self.jobs_list.delete(0, "end")
                self.job_row_ids = []
            if hasattr(self, "schedule_job_combo"):
                self.schedule_job_combo["values"] = []
            self._refresh_home_status()
            if show_error:
                messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)
            return
        if hasattr(self, "jobs_list"):
            self.jobs_list.delete(0, "end")
            self.job_row_ids = []
            totals = Counter(job.name for job in jobs)
            displayed: dict[str, int] = {}
            for job in jobs:
                displayed[job.name] = displayed.get(job.name, 0) + 1
                label = (
                    job.name if totals[job.name] == 1
                    else f"{job.name} ({displayed[job.name]}/{totals[job.name]})"
                )
                self.jobs_list.insert("end", label)
                self.job_row_ids.append(job.id)
            self._restore_list_selection()
        if hasattr(self, "schedule_job_combo"):
            self.schedule_job_combo["values"] = [f"{job.name} [{job.id}]" for job in jobs]
        self._refresh_home_status()

    def _visible_job_dirty(self) -> bool:
        if not self.selected_job_id:
            return any((
                self.job_name_var.get().strip(),
                self.blog_var.get().strip(),
                self.target_var.get().strip(),
                self.anchor_var.get().strip(),
                self.link_var.get().strip(),
            ))
        try:
            return needs_save(self.job_store.get(self.selected_job_id), self._form_job())
        except Exception:
            # An invalid partial edit is still unsaved work worth protecting.
            return True

    def _confirm_discard_input(self) -> bool:
        if not self._visible_job_dirty():
            return True
        return messagebox.askyesno(
            self.t("warning_title"), self.t("confirm_discard_edits"), parent=self.root
        )

    def _restore_list_selection(self) -> None:
        self.jobs_list.selection_clear(0, "end")
        if self.selected_job_id is None:
            return
        for index, job_id in enumerate(self.job_row_ids):
            if job_id == self.selected_job_id:
                self.jobs_list.selection_set(index)
                break

    def new_job(self, *, force: bool = False) -> None:
        if not force and (self._reject_if_busy() or not self._confirm_discard_input()):
            return
        self.selected_job_id = None
        self.job_name_var.set("")
        self.blog_var.set("")
        self.target_var.set("")
        self.anchor_var.set("")
        self.link_var.set("")
        self.max_posts_var.set("50")
        self.enabled_var.set(True)
        self.jobs_list.selection_clear(0, "end")
        self._refresh_home_status()

    @staticmethod
    def _id_from_display(display: str) -> str:
        if display.endswith("]") and "[" in display:
            return display.rsplit("[", 1)[1][:-1]
        return display

    def on_job_select(self, _event: object = None) -> None:
        if self.busy:
            self._restore_list_selection()
            self._reject_if_busy()
            return
        selection = self.jobs_list.curselection()
        if not selection:
            return
        if selection[0] >= len(self.job_row_ids):
            self._restore_list_selection()
            return
        next_id = self.job_row_ids[selection[0]]
        if next_id == self.selected_job_id:
            return
        if not self._confirm_discard_input():
            self._restore_list_selection()
            return
        try:
            self.load_job(next_id)
            self.selected_job_id = next_id
            self._refresh_home_status()
        except Exception as exc:
            self._restore_list_selection()
            messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)

    def load_job(self, job_id: str) -> None:
        job = self.job_store.get(job_id)
        self.job_name_var.set(job.name)
        self.blog_var.set(next((display for display, bid in self.blog_display_to_id.items() if bid == job.blog_id), job.blog_id))
        self.target_var.set(job.target_text)
        self.anchor_var.set(job.anchor_text)
        self.link_var.set(job.link_url)
        self.max_posts_var.set(str(job.max_posts))
        self.enabled_var.set(job.enabled)
        self._load_schedule_fields(job)

    def _form_job(self) -> BloggerLinkJob:
        blog_display = self.blog_var.get().strip()
        blog_id = self.blog_display_to_id.get(blog_display, blog_display)
        job_id = self.selected_job_id or uuid.uuid4().hex[:12]
        try:
            schedule = self.job_store.get(job_id).schedule
        except KeyError:
            schedule = ScheduleSpec()
        return BloggerLinkJob(
            id=job_id,
            name=self.job_name_var.get(),
            blog_id=blog_id,
            target_text=self.target_var.get(),
            link_url=self.link_var.get(),
            anchor_text=self.anchor_var.get() or self.target_var.get(),
            max_posts=int(self.max_posts_var.get()),
            enabled=self.enabled_var.get(),
            schedule=schedule,
        )

    def save_job(self) -> None:
        if self._reject_if_busy():
            return
        try:
            job = self._form_job()
            self.job_store.upsert(job)
            self.selected_job_id = job.id
            self.preview_revision = None
            self.refresh_jobs(show_error=False)
            messagebox.showinfo(self.t("info_title"), self.t("saved"))
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))

    def delete_job(self) -> None:
        if self._reject_if_busy():
            return
        if not self.selected_job_id:
            messagebox.showinfo(self.t("info_title"), self.t("select_job_first"))
            return
        if not messagebox.askyesno(self.t("warning_title"), self.t("confirm_delete")):
            return
        job_id = self.selected_job_id
        try:
            # If the Windows task cannot be removed, retain the rule to avoid
            # a phantom recurring task that the UI claims was deleted.
            self.scheduler.unregister(job_id)
            self.schedule_approvals.revoke(job_id)
            self.job_store.delete(job_id)
            self.preview_revision = None
            self.selected_job_id = None
            self.new_job(force=True)
            self.refresh_jobs(show_error=False)
            messagebox.showinfo(self.t("info_title"), self.t("deleted"))
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))

    def run_job(self, dry_run: bool) -> None:
        if self.busy:
            messagebox.showinfo(self.t("info_title"), self.t("busy_processing"), parent=self.root)
            return
        if not self.selected_job_id:
            messagebox.showinfo(self.t("info_title"), self.t("select_job_first"), parent=self.root)
            return
        try:
            job = self.job_store.get(self.selected_job_id)
            edited = self._form_job()
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)
            return
        if needs_save(job, edited):
            messagebox.showwarning(self.t("warning_title"), self.t("save_changes_first"), parent=self.root)
            return
        if not dry_run:
            ready, why = live_run_ready(
                job=job, edited=edited, preview_revision=self.preview_revision, busy=self.busy
            )
            if not ready:
                key = "preview_required_before_live" if why == "preview_required" else "save_changes_first"
                messagebox.showwarning(self.t("warning_title"), self.t(key), parent=self.root)
                return
            if not messagebox.askyesno(
                self.t("warning_title"), self.t("confirm_run"), parent=self.root
            ):
                return
            # A write may partly succeed remotely and then lose its response.
            # Consume this preview BEFORE attempting a mutating request,
            # not after a success callback that might never arrive.
            self.preview_revision = None
            self._refresh_home_status()
        self.run_async(
            lambda: run_link_job(self.google, job, dry_run=dry_run),
            lambda result: self._after_job_run(job, result, dry_run),
        )

    def _after_job_run(self, job: BloggerLinkJob, result: Any, dry_run: bool) -> None:
        if dry_run:
            self.preview_revision = job_revision(job)
        else:
            # Never permit a second write from one preview by accident.
            self.preview_revision = None
        self._refresh_home_status()
        messagebox.showinfo(
            self.t("info_title"),
            self.t("dry_result" if dry_run else "run_result", scanned=result.scanned, changed=result.changed),
            parent=self.root,
        )

    def on_schedule_job_select(self, _event: object = None) -> None:
        display = self.schedule_job_var.get()
        if display:
            try:
                # Scheduler selection must not silently change the job editor's
                # selected rule (and accidentally apply unsaved values to it).
                self.selected_schedule_job_id = self._id_from_display(display)
                self._load_schedule_fields(self.job_store.get(self.selected_schedule_job_id))
            except Exception as exc:
                messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)

    def _load_schedule_fields(self, job: BloggerLinkJob) -> None:
        if not hasattr(self, "schedule_kind_var"):
            return
        self.selected_schedule_job_id = job.id
        labels = {"daily": self.t("daily"), "weekly": self.t("weekly"), "logon": self.t("logon")}
        self.schedule_kind_var.set(labels.get(job.schedule.kind, self.t("daily")))
        self.schedule_time_var.set(job.schedule.time)
        for day, var in self.weekday_vars.items():
            var.set(day in job.schedule.weekdays)
        self.schedule_job_var.set(f"{job.name} [{job.id}]")

    def _schedule_from_fields(self) -> ScheduleSpec:
        reverse = {self.t("daily"): "daily", self.t("weekly"): "weekly", self.t("logon"): "logon"}
        return ScheduleSpec(
            kind=reverse.get(self.schedule_kind_var.get(), "daily"),
            time=self.schedule_time_var.get().strip(),
            weekdays=[day for day, var in self.weekday_vars.items() if var.get()],
        )

    def save_schedule_to_job(self, *, show_feedback: bool = True) -> BloggerLinkJob | None:
        if self._reject_if_busy():
            return None
        display = self.schedule_job_var.get()
        schedule_id = self._id_from_display(display) if display else self.selected_schedule_job_id
        if not schedule_id:
            messagebox.showinfo(self.t("info_title"), self.t("select_job_first"), parent=self.root)
            return None
        try:
            job = self.job_store.get(schedule_id)
            job.schedule = self._schedule_from_fields()
            self.job_store.upsert(job)
            self.refresh_jobs(show_error=False)
            if show_feedback:
                messagebox.showinfo(self.t("info_title"), self.t("saved"), parent=self.root)
            return job
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc))
            return None

    def register_schedule(self) -> None:
        if self.busy:
            messagebox.showinfo(self.t("info_title"), self.t("busy_processing"), parent=self.root)
            return
        display = self.schedule_job_var.get()
        job_id = self._id_from_display(display) if display else self.selected_schedule_job_id
        if not job_id:
            messagebox.showinfo(self.t("info_title"), self.t("select_job_first"), parent=self.root)
            return
        if self.selected_job_id == job_id and self._visible_job_dirty():
            messagebox.showwarning(
                self.t("warning_title"), self.t("save_changes_first"), parent=self.root
            )
            return
        try:
            saved = self.job_store.get(job_id)
            if self.preview_revision != job_revision(saved):
                messagebox.showwarning(
                    self.t("warning_title"), self.t("preview_required_before_schedule"), parent=self.root
                )
                return
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)
            return
        if not messagebox.askyesno(
            self.t("warning_title"), self.t("confirm_schedule_changes"), parent=self.root
        ):
            return
        job = self.save_schedule_to_job(show_feedback=False)
        if job is None:
            return
        try:
            self.scheduler.register(job)
            # Runner independently checks this review stamp on every live launch.
            self.schedule_approvals.authorize(job)
            messagebox.showinfo(self.t("info_title"), self.t("schedule_registered"), parent=self.root)
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)

    def remove_schedule(self) -> None:
        if self.busy:
            messagebox.showinfo(self.t("info_title"), self.t("busy_processing"), parent=self.root)
            return
        display = self.schedule_job_var.get()
        job_id = self._id_from_display(display) if display else self.selected_schedule_job_id
        if not job_id:
            messagebox.showinfo(self.t("info_title"), self.t("select_job_first"), parent=self.root)
            return
        try:
            self.scheduler.unregister(job_id)
            self.schedule_approvals.revoke(job_id)
            messagebox.showinfo(self.t("info_title"), self.t("schedule_removed"), parent=self.root)
        except Exception as exc:
            messagebox.showerror(self.t("error_title"), str(exc), parent=self.root)

    def test_scheduler(self) -> None:
        check = self.scheduler.check()
        self.scheduler_status_var.set(
            self.t("status_scheduler_ok") if check.ok else f"{self.t('status_scheduler_ng')}: {check.detail}"
        )


def launch_gui() -> None:
    root = Tk()
    AutomationHubGUI(root)
    root.mainloop()
