from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkflowError(RuntimeError):
    pass


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so an allowlisted URL cannot escape to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_env(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("${ENV:") and value.endswith("}"):
        name = value[6:-1]
        result = os.getenv(name)
        if result is None:
            raise WorkflowError(f"Required environment variable is not set: {name}")
        return result
    if isinstance(value, list):
        return [resolve_env(v) for v in value]
    if isinstance(value, dict):
        return {k: resolve_env(v) for k, v in value.items()}
    return value


class Runner:
    def __init__(self, config: dict[str, Any], dry_run: bool = False) -> None:
        self.config = resolve_env(config)
        self.dry_run = dry_run
        self.base_dir = Path(self.config.get("base_dir", ".")).expanduser().resolve()
        if not self.dry_run:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts = {str(x).lower() for x in self.config.get("allow_hosts", [])}
        self.log_path = Path(self.config.get("log_path", "logs/workflow.jsonl"))
        if not self.log_path.is_absolute():
            self.log_path = (self.base_dir / self.log_path).resolve()
        self._assert_under_base(self.log_path)

    def _assert_under_base(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.base_dir)
        except ValueError as exc:
            raise WorkflowError(f"Path is outside base_dir: {path}") from exc

    def _path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        path = path.resolve()
        self._assert_under_base(path)
        return path

    @staticmethod
    def _check_destination(dst: Path, overwrite: bool) -> None:
        if not dst.exists():
            return
        if dst.is_dir():
            raise WorkflowError(f"Destination is a directory: {dst}")
        if not overwrite:
            raise WorkflowError(f"Destination already exists and overwrite=false: {dst}")

    def log(self, event: dict[str, Any]) -> None:
        event = {"ts": utc_now(), **event}
        print(json.dumps(event, ensure_ascii=False))
        if self.dry_run:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def run(self) -> None:
        workflow = self.config.get("workflow")
        if not isinstance(workflow, list) or not workflow:
            raise WorkflowError("workflow must be a non-empty list")
        self.log({"event": "workflow_start", "dry_run": self.dry_run})
        for index, step in enumerate(workflow, start=1):
            if not isinstance(step, dict):
                raise WorkflowError(f"step {index} must be an object")
            action = step.get("action")
            self.log({"event": "step_start", "step": index, "action": action})
            self._run_step(action, step)
            self.log({"event": "step_ok", "step": index, "action": action})
        self.log({"event": "workflow_ok"})

    def _run_step(self, action: str | None, step: dict[str, Any]) -> None:
        handlers = {
            "copy_file": self._copy_file,
            "move_file": self._move_file,
            "write_text": self._write_text,
            "http_request": self._http_request,
        }
        handler = handlers.get(action or "")
        if handler is None:
            raise WorkflowError(f"Unsupported action: {action}")
        handler(step)

    def _copy_file(self, step: dict[str, Any]) -> None:
        src = self._path(str(step["src"]))
        dst = self._path(str(step["dst"]))
        overwrite = bool(step.get("overwrite", False))
        if self.dry_run:
            return
        if not src.is_file():
            raise WorkflowError(f"Source file does not exist: {src}")
        self._check_destination(dst, overwrite)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def _move_file(self, step: dict[str, Any]) -> None:
        src = self._path(str(step["src"]))
        dst = self._path(str(step["dst"]))
        overwrite = bool(step.get("overwrite", False))
        if self.dry_run:
            return
        if not src.is_file():
            raise WorkflowError(f"Source file does not exist: {src}")
        self._check_destination(dst, overwrite)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and overwrite:
            dst.unlink()
        shutil.move(str(src), str(dst))

    def _write_text(self, step: dict[str, Any]) -> None:
        dst = self._path(str(step["path"]))
        text = str(step.get("text", ""))
        overwrite = bool(step.get("overwrite", False))
        if self.dry_run:
            return
        self._check_destination(dst, overwrite)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")

    def _http_request(self, step: dict[str, Any]) -> None:
        url = str(step["url"])
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise WorkflowError("Only HTTPS API calls are allowed")
        if not host or host not in self.allowed_hosts:
            raise WorkflowError(f"Host is not in allow_hosts: {host}")

        method = str(step.get("method", "GET")).upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise WorkflowError(f"Unsupported HTTP method: {method}")
        if self.dry_run:
            return

        headers = {str(k): str(v) for k, v in step.get("headers", {}).items()}
        data = None
        if "json" in step:
            data = json.dumps(step["json"]).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        timeout = float(step.get("timeout_seconds", 30))
        opener = urllib.request.build_opener(_RejectRedirectHandler())
        try:
            with opener.open(request, timeout=timeout) as response:
                final = urllib.parse.urlparse(response.geturl())
                final_host = (final.hostname or "").lower()
                if final.scheme != "https" or final_host != host:
                    raise WorkflowError("HTTP response URL changed unexpectedly")
                body = response.read(1_000_000)
                self.log({"event": "http_response", "status": response.status, "host": host, "bytes": len(body)})
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise WorkflowError(f"Redirect responses are not allowed for {host}") from exc
            raise WorkflowError(f"HTTP {exc.code} from {host}") from exc
        except urllib.error.URLError as exc:
            raise WorkflowError(f"Request failed for {host}: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic local workflow runner")
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        Runner(config, dry_run=args.dry_run).run()
        return 0
    except (OSError, json.JSONDecodeError, KeyError, WorkflowError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
