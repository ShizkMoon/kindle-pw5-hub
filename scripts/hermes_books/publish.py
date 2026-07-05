from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import posixpath
import urllib.error
from urllib.parse import quote
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import BookManifest, UpdateDecision


class WebDavClient(Protocol):
    def exists(self, path: str) -> bool:
        ...

    def get(self, path: str) -> bytes:
        ...

    def put(self, path: str, data: bytes) -> None:
        ...

    def mkdir(self, path: str) -> None:
        ...


class LocalWebDavClient:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, path: str) -> Path:
        stripped = path.strip("/")
        if not stripped or "\\" in path:
            raise ValueError(f"invalid WebDAV path: {path!r}")

        segments = stripped.split("/")
        if any(
            not segment
            or segment == ".."
            or (len(segment) >= 2 and segment[0].isalpha() and segment[1] == ":")
            for segment in segments
        ):
            raise ValueError(f"invalid WebDAV path: {path!r}")

        target = (self.root / posixpath.join(*segments)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"WebDAV path escapes root: {path!r}") from exc
        return target

    def exists(self, path: str) -> bool:
        return self._path(path).exists()

    def get(self, path: str) -> bytes:
        return self._path(path).read_bytes()

    def put(self, path: str, data: bytes) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def mkdir(self, path: str) -> None:
        self._path(path).mkdir(parents=True, exist_ok=True)


class HttpWebDavClient:
    def __init__(self, base_url: str, username: str = "", password: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _quote_path(self, path: str) -> str:
        return quote(path.strip("/"), safe="/")

    def _request(self, path: str, method: str, data: bytes | None = None) -> bytes:
        url = self.base_url + "/" + self._quote_path(path)
        req = urllib.request.Request(url, data=data, method=method)
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(path) from exc
            raise

    def exists(self, path: str) -> bool:
        try:
            self._request(path, "HEAD")
            return True
        except FileNotFoundError:
            return False

    def get(self, path: str) -> bytes:
        return self._request(path, "GET")

    def put(self, path: str, data: bytes) -> None:
        self._request(path, "PUT", data)

    def mkdir(self, path: str) -> None:
        current = ""
        for segment in path.strip("/").split("/"):
            if not segment:
                continue
            current = f"{current}/{segment}"
            try:
                self._request(current, "MKCOL")
            except urllib.error.HTTPError as exc:
                if exc.code != 405:
                    raise


class WebDavPublisher:
    def __init__(self, client: WebDavClient, timestamp: Callable[[], str] | None = None) -> None:
        self.client = client
        self.timestamp = timestamp or self._utc_timestamp

    def _utc_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _backup_dir(self, target_epub_path: str, slug: str) -> str:
        backup_root = posixpath.join(posixpath.dirname(target_epub_path), ".backups", slug)
        timestamp = self.timestamp()
        backup_dir = posixpath.join(backup_root, timestamp)
        suffix = 2
        while self.client.exists(posixpath.join(backup_dir, "old.epub")):
            backup_dir = posixpath.join(backup_root, f"{timestamp}-{suffix}")
            suffix += 1
        return backup_dir

    def _pending_update(
        self,
        target_epub_path: str,
        epub_path: Path,
        manifest: BookManifest,
        decision_value: str,
        reason: str | None = None,
    ) -> dict[str, str]:
        slug = Path(target_epub_path).stem
        pending_dir = posixpath.join(posixpath.dirname(target_epub_path), ".pending", slug)
        self.client.mkdir(pending_dir)
        self.client.put(posixpath.join(pending_dir, "candidate.epub"), epub_path.read_bytes())
        self.client.put(
            posixpath.join(pending_dir, "candidate.hermes.json"),
            manifest.to_json().encode("utf-8"),
        )
        self.client.put(
            posixpath.join(pending_dir, "risk-report.md"),
            (
                "# Pending update\n\n"
                f"Decision: {decision_value}\n"
                + (f"Reason: {reason}\n" if reason else "")
            ).encode("utf-8"),
        )
        report = {"status": "pending", "path": pending_dir}
        if reason:
            report["reason"] = reason
        return report

    def publish(
        self,
        target_epub_path: str,
        epub_path: Path,
        manifest: BookManifest,
        *,
        expected_old_epub_hash: str | None = None,
        expected_old_manifest_hash: str | None = None,
    ) -> dict[str, str]:
        slug = Path(target_epub_path).stem
        manifest_path = target_epub_path[:-5] + ".hermes.json"
        decision = manifest.update_decision
        decision_value = decision.value if isinstance(decision, UpdateDecision) else str(decision)
        safe_overwrite_decisions = {UpdateDecision.SAFE_APPEND.value, UpdateDecision.SAFE_METADATA.value}

        if decision_value in {UpdateDecision.BLOCKED_RISKY.value, UpdateDecision.REVIEW_MINOR.value}:
            return self._pending_update(target_epub_path, epub_path, manifest, decision_value)

        target_exists = self.client.exists(target_epub_path)
        if target_exists and decision_value not in safe_overwrite_decisions:
            return self._pending_update(target_epub_path, epub_path, manifest, decision_value)

        old_epub_bytes: bytes | None = None
        old_manifest_bytes: bytes | None = None
        had_manifest = False
        if target_exists:
            had_manifest = self.client.exists(manifest_path)
            if not had_manifest:
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "existing target has no Hermes manifest",
                )
            if expected_old_epub_hash is None or expected_old_manifest_hash is None:
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "existing target overwrite requires expected old remote hashes",
                )
            try:
                old_manifest_bytes = self.client.get(manifest_path)
                old_epub_bytes = self.client.get(target_epub_path)
            except Exception:
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "existing target or manifest unreadable",
                )
            current_epub_hash = hashlib.sha256(old_epub_bytes).hexdigest()
            current_manifest_hash = hashlib.sha256(old_manifest_bytes).hexdigest()
            if (
                current_epub_hash != expected_old_epub_hash
                or current_manifest_hash != expected_old_manifest_hash
            ):
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "existing target changed since update diff",
                )
            backup_dir = self._backup_dir(target_epub_path, slug)
            self.client.mkdir(backup_dir)
            self.client.put(posixpath.join(backup_dir, "old.epub"), old_epub_bytes)
            if had_manifest and old_manifest_bytes is not None:
                self.client.put(posixpath.join(backup_dir, "old.hermes.json"), old_manifest_bytes)

        try:
            self.client.put(target_epub_path, epub_path.read_bytes())
            self.client.put(manifest_path, manifest.to_json().encode("utf-8"))
        except Exception:
            if target_exists and old_epub_bytes is not None:
                self.client.put(target_epub_path, old_epub_bytes)
                if had_manifest and old_manifest_bytes is not None:
                    self.client.put(manifest_path, old_manifest_bytes)
            raise
        return {"status": "published", "path": target_epub_path}
