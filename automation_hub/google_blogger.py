from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .paths import google_client_config_path, token_path
from .storage import DPAPITokenVault, SecureStoreError

BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
SCOPES = [BLOGGER_SCOPE]
GOOGLE_AUTH_URIS = {
    "https://accounts.google.com/o/oauth2/auth",
}
GOOGLE_TOKEN_URIS = {
    "https://oauth2.googleapis.com/token",
    "https://accounts.google.com/o/oauth2/token",
}
MAX_CLIENT_JSON_BYTES = 64 * 1024
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class GoogleBloggerError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleClientMetadata:
    client_id: str
    project_id: str = ""

    @property
    def client_id_hint(self) -> str:
        if len(self.client_id) <= 24:
            return self.client_id
        return f"{self.client_id[:12]}…{self.client_id[-12:]}"


@dataclass(frozen=True)
class ClientImportResult:
    metadata: GoogleClientMetadata
    token_reset: bool


@dataclass
class ConnectionResult:
    ok: bool
    blogs: list[dict[str, str]]
    detail: str = ""


def _require_nonempty_string(obj: dict[str, Any], key: str, *, max_length: int = 4096) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GoogleBloggerError(f"OAuth JSON is missing '{key}' / OAuth JSONに'{key}'がありません")
    value = value.strip()
    if len(value) > max_length:
        raise GoogleBloggerError(f"OAuth JSON field '{key}' is too long / OAuth JSONの'{key}'が長すぎます")
    return value


def _validate_loopback_redirect(raw_uri: str) -> None:
    parsed = urlparse(raw_uri)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise GoogleBloggerError(
            "Desktop OAuth redirect URI must be a local loopback address / "
            "Desktop OAuthのredirect URIはlocalhost/loopbackである必要があります"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GoogleBloggerError("Desktop OAuth redirect URI contains unsupported components / redirect URIの形式が不正です")


def validate_google_desktop_client_config(config: Any) -> GoogleClientMetadata:
    if not isinstance(config, dict):
        raise GoogleBloggerError("OAuth JSON root must be an object / OAuth JSONのルートはオブジェクトである必要があります")
    if "installed" not in config:
        if "web" in config:
            raise GoogleBloggerError(
                "This is a Web application OAuth JSON. Create a Google OAuth client with Application type 'Desktop app'. / "
                "これはWeb application用OAuth JSONです。Application typeを'Desktop app'にして作成してください"
            )
        raise GoogleBloggerError(
            "Only Google OAuth Desktop app JSON is supported (missing 'installed'). / "
            "Google OAuthのDesktop app用JSONのみ対応しています（'installed'がありません）"
        )
    installed = config.get("installed")
    if not isinstance(installed, dict):
        raise GoogleBloggerError("OAuth JSON 'installed' must be an object / 'installed'の形式が不正です")

    client_id = _require_nonempty_string(installed, "client_id", max_length=512)
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise GoogleBloggerError("Google OAuth client_id format is invalid / Google OAuth client_idの形式が不正です")
    _require_nonempty_string(installed, "client_secret", max_length=1024)
    auth_uri = _require_nonempty_string(installed, "auth_uri", max_length=512)
    token_uri = _require_nonempty_string(installed, "token_uri", max_length=512)
    if auth_uri not in GOOGLE_AUTH_URIS:
        raise GoogleBloggerError("Unexpected Google auth_uri / Google auth_uriが想定値と異なります")
    if token_uri not in GOOGLE_TOKEN_URIS:
        raise GoogleBloggerError("Unexpected Google token_uri / Google token_uriが想定値と異なります")

    # Google's downloaded installed-app examples normally include redirect_uris,
    # but client-secret format documentation treats fields other than client_id
    # and client_secret as potentially optional. run_local_server supplies its
    # own loopback redirect, so absence is accepted; any supplied URI is still
    # restricted to a local loopback address.
    redirect_uris = installed.get("redirect_uris")
    if redirect_uris is not None:
        if not isinstance(redirect_uris, list) or not redirect_uris:
            raise GoogleBloggerError("redirect_uris must be a non-empty list when present / redirect_urisの形式が不正です")
        for raw_uri in redirect_uris:
            if not isinstance(raw_uri, str) or not raw_uri.strip():
                raise GoogleBloggerError("redirect_uris contains an invalid value / redirect_urisの形式が不正です")
            _validate_loopback_redirect(raw_uri.strip())

    project_id = installed.get("project_id", "")
    if project_id is None:
        project_id = ""
    if not isinstance(project_id, str) or len(project_id) > 256:
        raise GoogleBloggerError("OAuth JSON project_id is invalid / OAuth JSONのproject_idが不正です")
    return GoogleClientMetadata(client_id=client_id, project_id=project_id.strip())


def load_google_desktop_client_file(path: Path) -> tuple[dict[str, Any], GoogleClientMetadata]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise GoogleBloggerError(f"OAuth credentials file not found / OAuth設定ファイルが見つかりません: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GoogleBloggerError(f"Cannot inspect OAuth JSON / OAuth JSONを確認できません: {exc}") from exc
    if size <= 0 or size > MAX_CLIENT_JSON_BYTES:
        raise GoogleBloggerError("OAuth JSON file size is invalid / OAuth JSONのファイルサイズが不正です")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleBloggerError(f"OAuth JSON cannot be read / OAuth JSONを読み込めません: {exc}") from exc
    metadata = validate_google_desktop_client_config(raw)
    return raw, metadata


class GoogleBloggerConnector:
    def __init__(
        self,
        token_vault: DPAPITokenVault | None = None,
        client_vault: DPAPITokenVault | None = None,
    ) -> None:
        self.token_vault = token_vault or DPAPITokenVault(token_path())
        self.client_vault = client_vault or DPAPITokenVault(google_client_config_path())

    def has_client_config(self) -> bool:
        return self.client_vault.exists()

    def has_token(self) -> bool:
        return self.token_vault.exists()

    def _load_client_config(self) -> tuple[dict[str, Any], GoogleClientMetadata]:
        try:
            raw = self.client_vault.load_text()
        except SecureStoreError as exc:
            raise GoogleBloggerError(f"Stored OAuth client configuration cannot be decrypted / 保存済みOAuth設定を復号できません: {exc}") from exc
        if not raw:
            raise GoogleBloggerError(
                "Google OAuth Desktop app JSON has not been imported / Google OAuth Desktop app用JSONがインポートされていません"
            )
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleBloggerError("Stored OAuth client configuration is corrupted / 保存済みOAuth設定が破損しています") from exc
        metadata = validate_google_desktop_client_config(config)
        return config, metadata

    def client_metadata(self) -> GoogleClientMetadata:
        return self._load_client_config()[1]

    def _stored_token_client_id(self) -> str:
        raw = self.token_vault.load_text()
        if not raw:
            return ""
        info = json.loads(raw)
        if not isinstance(info, dict):
            return ""
        value = info.get("client_id", "")
        return str(value).strip()

    def import_client_config(self, source: Path) -> ClientImportResult:
        config, metadata = load_google_desktop_client_file(source)
        token_reset = False
        if self.token_vault.exists():
            try:
                existing_token_client_id = self._stored_token_client_id()
            except (SecureStoreError, json.JSONDecodeError, UnicodeError, ValueError):
                existing_token_client_id = ""
            if not existing_token_client_id or existing_token_client_id != metadata.client_id:
                try:
                    self.token_vault.delete()
                except SecureStoreError as exc:
                    raise GoogleBloggerError(f"Could not clear incompatible Google token / 古いGoogleトークンを削除できません: {exc}") from exc
                token_reset = True
        try:
            self.client_vault.save_text(json.dumps(config, ensure_ascii=False, separators=(",", ":")))
        except SecureStoreError as exc:
            raise GoogleBloggerError(f"Could not securely import OAuth configuration / OAuth設定を安全に保存できません: {exc}") from exc
        return ClientImportResult(metadata=metadata, token_reset=token_reset)

    def authenticate(self, locale: str = "ja") -> Credentials:
        config, _metadata = self._load_client_config()
        try:
            flow = InstalledAppFlow.from_client_config(config, SCOPES)
            success = (
                "Authentication completed. You may close this window."
                if locale == "en"
                else "認証が完了しました。このウィンドウを閉じて構いません。"
            )
            credentials = flow.run_local_server(
                port=0,
                open_browser=True,
                access_type="offline",
                prompt="consent",
                success_message=success,
            )
            self.token_vault.save_text(credentials.to_json())
            return credentials
        except (ValueError, OSError, SecureStoreError) as exc:
            raise GoogleBloggerError(f"Google authentication failed / Google認証に失敗しました: {exc}") from exc

    def disconnect(self) -> None:
        try:
            self.token_vault.delete()
        except SecureStoreError as exc:
            raise GoogleBloggerError(str(exc)) from exc

    def remove_client_config(self) -> None:
        try:
            self.token_vault.delete()
            self.client_vault.delete()
        except SecureStoreError as exc:
            raise GoogleBloggerError(str(exc)) from exc

    def _load_credentials(self) -> Credentials:
        try:
            raw = self.token_vault.load_text()
        except SecureStoreError as exc:
            raise GoogleBloggerError(f"Stored Google token cannot be decrypted / 保存済みGoogleトークンを復号できません: {exc}") from exc
        if not raw:
            raise GoogleBloggerError("Google account is not authenticated / Googleアカウントが認証されていません")
        try:
            info = json.loads(raw)
            credentials = Credentials.from_authorized_user_info(info, SCOPES)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.token_vault.save_text(credentials.to_json())
        except (json.JSONDecodeError, ValueError, RefreshError, TransportError, OSError, SecureStoreError) as exc:
            raise GoogleBloggerError(
                f"Google credentials are invalid or expired; reconnect the account / Google認証情報が無効です。再接続してください: {exc}"
            ) from exc
        if not credentials.valid:
            raise GoogleBloggerError("Google credentials are not valid; reconnect the account / Googleを再接続してください")
        return credentials

    def _service(self):
        try:
            return build("blogger", "v3", credentials=self._load_credentials(), cache_discovery=False)
        except Exception as exc:
            if isinstance(exc, GoogleBloggerError):
                raise
            raise GoogleBloggerError(f"Could not create Blogger API client / Blogger APIクライアントを作成できません: {exc}") from exc

    def check_connection(self) -> ConnectionResult:
        try:
            response = self._service().blogs().listByUser(userId="self").execute(num_retries=2)
            blogs = [
                {"id": str(item.get("id", "")), "name": str(item.get("name", "")), "url": str(item.get("url", ""))}
                for item in response.get("items", [])
            ]
            return ConnectionResult(True, blogs, "ok")
        except GoogleBloggerError:
            raise
        except (HttpError, OSError, ValueError) as exc:
            raise GoogleBloggerError(f"Blogger API connection failed / Blogger API接続に失敗しました: {exc}") from exc

    def list_blogs(self) -> list[dict[str, str]]:
        return self.check_connection().blogs

    def list_posts(self, blog_id: str, status: str = "LIVE", max_posts: int = 50) -> list[dict[str, Any]]:
        service = self._service()
        collected: list[dict[str, Any]] = []
        page_token: str | None = None
        remaining = max(1, min(int(max_posts), 500))
        while remaining > 0:
            batch = min(remaining, 50)
            try:
                response = service.posts().list(
                    blogId=blog_id, status=[status], maxResults=batch, fetchBodies=True, pageToken=page_token
                ).execute(num_retries=2)
            except HttpError as exc:
                raise GoogleBloggerError(f"Could not list Blogger posts / Blogger記事一覧を取得できません: {exc}") from exc
            items = response.get("items", [])
            if not isinstance(items, list):
                raise GoogleBloggerError("Unexpected Blogger API response / Blogger API応答形式が不正です")
            take = items[:remaining]
            collected.extend(take)
            remaining -= len(take)
            page_token = response.get("nextPageToken")
            if not page_token or not items:
                break
        return collected

    def patch_post_content(self, blog_id: str, post_id: str, content: str) -> dict[str, Any]:
        try:
            return self._service().posts().patch(
                blogId=blog_id, postId=post_id, body={"content": content}, fetchBody=False
            ).execute(num_retries=0)  # No automatic replay of a mutating request.
        except HttpError as exc:
            raise GoogleBloggerError(f"Could not update Blogger post / Blogger記事を更新できません: {exc}") from exc
