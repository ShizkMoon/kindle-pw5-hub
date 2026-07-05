from __future__ import annotations

import base64
import posixpath
import urllib.error
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
        self.root = root

    def _path(self, path: str) -> Path:
        return self.root / path.strip("/")

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

    def _request(self, path: str, method: str, data: bytes | None = None) -> bytes:
        url = self.base_url + "/" + path.strip("/")
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
        try:
            self._request(path, "MKCOL")
        except urllib.error.HTTPError as exc:
            if exc.code not in {405, 409}:
                raise


class WebDavPublisher:
    def __init__(self, client: WebDavClient) -> None:
        self.client = client

    def publish(self, target_epub_path: str, epub_path: Path, manifest: BookManifest) -> dict[str, str]:
        slug = Path(target_epub_path).stem
        manifest_path = target_epub_path[:-5] + ".hermes.json"
        decision = manifest.update_decision

        if decision in {UpdateDecision.BLOCKED_RISKY, UpdateDecision.REVIEW_MINOR}:
            pending_dir = posixpath.join(posixpath.dirname(target_epub_path), ".pending", slug)
            self.client.mkdir(pending_dir)
            self.client.put(posixpath.join(pending_dir, "candidate.epub"), epub_path.read_bytes())
            self.client.put(
                posixpath.join(pending_dir, "candidate.hermes.json"),
                manifest.to_json().encode("utf-8"),
            )
            self.client.put(
                posixpath.join(pending_dir, "risk-report.md"),
                f"# Pending update\n\nDecision: {decision.value}\n".encode("utf-8"),
            )
            return {"status": "pending", "path": pending_dir}

        if self.client.exists(target_epub_path):
            backup_dir = posixpath.join(posixpath.dirname(target_epub_path), ".backups", slug)
            self.client.mkdir(backup_dir)
            self.client.put(posixpath.join(backup_dir, "old.epub"), self.client.get(target_epub_path))
            if self.client.exists(manifest_path):
                self.client.put(posixpath.join(backup_dir, "old.hermes.json"), self.client.get(manifest_path))

        self.client.put(target_epub_path, epub_path.read_bytes())
        self.client.put(manifest_path, manifest.to_json().encode("utf-8"))
        return {"status": "published", "path": target_epub_path}
