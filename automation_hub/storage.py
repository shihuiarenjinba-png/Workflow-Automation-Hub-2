from __future__ import annotations

import ctypes
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from .paths import token_path

CRYPTPROTECT_UI_FORBIDDEN = 0x1
MAX_VAULT_BYTES = 2 * 1024 * 1024


class SecureStoreError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _input_blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _windows_apis():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _raise_last_error(operation: str) -> None:
    code = ctypes.get_last_error()
    detail = str(ctypes.WinError(code)) if code else "unknown Windows error"
    raise SecureStoreError(f"{operation} failed / {operation}に失敗しました: {detail}")


class DPAPITokenVault:
    """Small current-user Windows DPAPI encrypted text vault."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or token_path()

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise SecureStoreError("Windows DPAPI is available only on Windows / Windowsでのみ利用できます")

    def save_text(self, text: str) -> None:
        self._require_windows()
        raw = text.encode("utf-8")
        if len(raw) > MAX_VAULT_BYTES:
            raise SecureStoreError("Vault payload is too large / 暗号化保存データが大きすぎます")
        crypt32, kernel32 = _windows_apis()
        in_blob, _buffer = _input_blob(raw)
        out_blob = _DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), "WorkflowAutomationHub", None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
        )
        if not ok:
            _raise_last_error("CryptProtectData")
        try:
            encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(encrypted)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_name, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load_text(self) -> str | None:
        if not self.path.exists():
            return None
        self._require_windows()
        try:
            size = self.path.stat().st_size
        except OSError as exc:
            raise SecureStoreError(f"Cannot read vault metadata / 暗号化保存領域を確認できません: {exc}") from exc
        if size <= 0 or size > MAX_VAULT_BYTES:
            raise SecureStoreError("Vault file size is invalid / 暗号化保存ファイルのサイズが不正です")
        encrypted = self.path.read_bytes()
        crypt32, kernel32 = _windows_apis()
        in_blob, _buffer = _input_blob(encrypted)
        out_blob = _DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
        )
        if not ok:
            _raise_last_error("CryptUnprotectData")
        try:
            decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))
        try:
            return decrypted.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecureStoreError("Vault content is not valid UTF-8 / 暗号化保存内容が不正です") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecureStoreError(f"Could not delete vault / 暗号化保存情報を削除できません: {exc}") from exc

    def exists(self) -> bool:
        return self.path.is_file()
