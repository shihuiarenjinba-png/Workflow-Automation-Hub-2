from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
SCHEDULE_KINDS = {"daily", "weekly", "logon"}
BLOGGER_STATUSES = {"LIVE", "DRAFT", "SCHEDULED"}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ModelValidationError(ValueError):
    pass


def validate_job_id(value: str) -> str:
    value = str(value).strip()
    if not JOB_ID_RE.fullmatch(value):
        raise ModelValidationError(
            "Job ID must contain only A-Z, a-z, 0-9, '_', '-', '.' and be 1-64 characters / "
            "ジョブIDは英数字・_-.のみ、1〜64文字で指定してください"
        )
    return value


def validate_time(value: str) -> str:
    value = str(value).strip()
    if not TIME_RE.fullmatch(value):
        raise ModelValidationError(
            "Time must use HH:MM (24-hour) format / 時刻は24時間制のHH:MM形式で指定してください"
        )
    return value


def _bounded_text(value: str, field_name: str, *, minimum: int = 1, maximum: int) -> str:
    value = str(value).strip()
    if not minimum <= len(value) <= maximum:
        raise ModelValidationError(
            f"{field_name} must be {minimum}-{maximum} characters / {field_name}は{minimum}〜{maximum}文字で指定してください"
        )
    return value


def validate_link_url(value: str) -> str:
    value = str(value).strip()
    if len(value) > 2048:
        raise ModelValidationError("Link URL is too long / リンクURLが長すぎます")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ModelValidationError(
            "Link URL must be an absolute http/https URL / リンクURLはhttp/httpsの絶対URLで指定してください"
        )
    if parsed.username or parsed.password:
        raise ModelValidationError("Credentials are not allowed in link URLs / リンクURLに認証情報は含められません")
    return value


@dataclass
class ScheduleSpec:
    kind: str = "daily"
    time: str = "08:00"
    weekdays: list[str] = field(default_factory=lambda: ["MON", "TUE", "WED", "THU", "FRI"])

    def __post_init__(self) -> None:
        self.kind = str(self.kind).strip().lower()
        if self.kind not in SCHEDULE_KINDS:
            raise ModelValidationError(f"Unsupported schedule kind / 未対応のスケジュール種別: {self.kind}")
        self.time = validate_time(self.time)
        normalized: list[str] = []
        for value in self.weekdays:
            day = str(value).strip().upper()
            if day not in WEEKDAYS:
                raise ModelValidationError(f"Invalid weekday / 曜日が不正です: {day}")
            if day not in normalized:
                normalized.append(day)
        self.weekdays = normalized
        if self.kind == "weekly" and not self.weekdays:
            raise ModelValidationError("At least one weekday is required / 曜日を1つ以上選択してください")

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ScheduleSpec":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ModelValidationError("schedule must be an object / scheduleはオブジェクトで指定してください")
        weekdays = raw.get("weekdays", ["MON", "TUE", "WED", "THU", "FRI"])
        if not isinstance(weekdays, list):
            raise ModelValidationError("weekdays must be a list / weekdaysはリストで指定してください")
        return cls(
            kind=str(raw.get("kind", "daily")),
            time=str(raw.get("time", "08:00")),
            weekdays=[str(x) for x in weekdays],
        )


@dataclass
class BloggerLinkJob:
    id: str
    name: str
    blog_id: str
    target_text: str
    link_url: str
    anchor_text: str
    max_posts: int = 50
    status: str = "LIVE"
    enabled: bool = True
    schedule: ScheduleSpec = field(default_factory=ScheduleSpec)

    def __post_init__(self) -> None:
        self.id = validate_job_id(self.id)
        self.name = _bounded_text(self.name, "name", maximum=120)
        self.blog_id = _bounded_text(self.blog_id, "blog_id", maximum=128)
        self.target_text = _bounded_text(self.target_text, "target_text", maximum=512)
        self.anchor_text = _bounded_text(self.anchor_text or self.target_text, "anchor_text", maximum=512)
        self.link_url = validate_link_url(self.link_url)
        try:
            self.max_posts = int(self.max_posts)
        except (TypeError, ValueError) as exc:
            raise ModelValidationError("max_posts must be an integer / 最大確認記事数は整数で指定してください") from exc
        if not 1 <= self.max_posts <= 500:
            raise ModelValidationError("max_posts must be 1-500 / 最大確認記事数は1〜500で指定してください")
        self.status = str(self.status).strip().upper()
        if self.status not in BLOGGER_STATUSES:
            raise ModelValidationError(f"Unsupported Blogger status / 未対応のBlogger状態: {self.status}")
        self.enabled = bool(self.enabled)
        if not isinstance(self.schedule, ScheduleSpec):
            self.schedule = ScheduleSpec.from_dict(self.schedule)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BloggerLinkJob":
        if not isinstance(raw, dict):
            raise ModelValidationError("Job must be an object / ジョブはオブジェクトで指定してください")
        try:
            target = str(raw["target_text"])
            return cls(
                id=str(raw["id"]),
                name=str(raw.get("name", raw["id"])),
                blog_id=str(raw["blog_id"]),
                target_text=target,
                link_url=str(raw["link_url"]),
                anchor_text=str(raw.get("anchor_text") or target),
                max_posts=int(raw.get("max_posts", 50)),
                status=str(raw.get("status", "LIVE")),
                enabled=bool(raw.get("enabled", True)),
                schedule=ScheduleSpec.from_dict(raw.get("schedule")),
            )
        except KeyError as exc:
            raise ModelValidationError(f"Missing job field / ジョブ項目がありません: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
