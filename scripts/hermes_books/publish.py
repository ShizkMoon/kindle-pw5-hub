from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import posixpath
import urllib.error
import uuid
from urllib.parse import quote
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import BookManifest, UpdateDecision


@dataclass(frozen=True)
class WebDavResource:
    exists: bool
    etag: str | None = None


@dataclass(frozen=True)
class WebDavWriteResult:
    etag: str | None = None


@dataclass(frozen=True)
class _WebDavResponse:
    body: bytes
    etag: str | None = None


@dataclass(frozen=True)
class _ExistingRemote:
    epub_bytes: bytes
    manifest_bytes: bytes
    epub_etag: str
    manifest_etag: str


class ConditionalWriteFailed(RuntimeError):
    pass


class ConditionalWriteUnsupported(RuntimeError):
    pass


class WebDavClient(Protocol):
    def stat(self, path: str) -> WebDavResource:
        ...

    def exists(self, path: str) -> bool:
        ...

    def get(self, path: str) -> bytes:
        ...

    def put(self, path: str, data: bytes) -> None:
        ...

    def put_if_absent(self, path: str, data: bytes) -> WebDavWriteResult:
        ...

    def put_if_match(self, path: str, data: bytes, etag: str) -> WebDavWriteResult:
        ...

    def delete_if_match(self, path: str, etag: str) -> None:
        ...

    def mkdir(self, path: str) -> None:
        ...


class LocalWebDavClient:
    supports_new_publish = True
    # A filesystem adapter cannot enforce WebDAV-style CAS against arbitrary
    # external writers, so existing-book live overwrites stay disabled by default.
    supports_existing_overwrite = False

    def __init__(self, root: Path, *, allow_existing_overwrite: bool | None = None) -> None:
        self.root = root.resolve()
        if allow_existing_overwrite is None:
            allow_existing_overwrite = type(self).supports_existing_overwrite
        self.supports_existing_overwrite = allow_existing_overwrite

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

    def _etag(self, data: bytes) -> str:
        return f'"{hashlib.sha256(data).hexdigest()}"'

    def stat(self, path: str) -> WebDavResource:
        target = self._path(path)
        if not target.exists():
            return WebDavResource(False)
        if not target.is_file():
            return WebDavResource(True)
        return WebDavResource(True, self._etag(target.read_bytes()))

    def exists(self, path: str) -> bool:
        return self.stat(path).exists

    def get(self, path: str) -> bytes:
        return self._path(path).read_bytes()

    def put(self, path: str, data: bytes) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def put_if_absent(self, path: str, data: bytes) -> WebDavWriteResult:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as fh:
                fh.write(data)
        except FileExistsError as exc:
            raise ConditionalWriteFailed(f"{path} already exists") from exc
        return WebDavWriteResult(self._etag(data))

    def put_if_match(self, path: str, data: bytes, etag: str) -> WebDavWriteResult:
        target = self._path(path)
        state = self.stat(path)
        if not state.exists or state.etag != etag:
            raise ConditionalWriteFailed(f"{path} changed before conditional write")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return WebDavWriteResult(self._etag(data))

    def delete_if_match(self, path: str, etag: str) -> None:
        target = self._path(path)
        state = self.stat(path)
        if not state.exists or state.etag != etag:
            raise ConditionalWriteFailed(f"{path} changed before conditional delete")
        target.unlink()

    def mkdir(self, path: str) -> None:
        self._path(path).mkdir(parents=True, exist_ok=True)


class HttpWebDavClient:
    supports_new_publish = True
    supports_existing_overwrite = True

    def __init__(self, base_url: str, username: str = "", password: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _quote_path(self, path: str) -> str:
        return quote(path.strip("/"), safe="/")

    def _strong_etag(self, raw_etag: str | None) -> str | None:
        if not raw_etag:
            return None
        etag = raw_etag.strip()
        if not etag or etag.startswith("W/"):
            return None
        return etag

    def _request(
        self,
        path: str,
        method: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> _WebDavResponse:
        url = self.base_url + "/" + self._quote_path(path)
        req = urllib.request.Request(url, data=data, method=method)
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                response_headers = getattr(resp, "headers", {})
                raw_etag = response_headers.get("ETag") if hasattr(response_headers, "get") else None
                return _WebDavResponse(resp.read(), self._strong_etag(raw_etag))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(path) from exc
            if exc.code == 412:
                raise ConditionalWriteFailed(f"{path} conditional write failed") from exc
            raise

    def stat(self, path: str) -> WebDavResource:
        try:
            response = self._request(path, "HEAD")
            return WebDavResource(True, response.etag)
        except FileNotFoundError:
            return WebDavResource(False)

    def exists(self, path: str) -> bool:
        return self.stat(path).exists

    def get(self, path: str) -> bytes:
        return self._request(path, "GET").body

    def put(self, path: str, data: bytes) -> None:
        self._request(path, "PUT", data)

    def put_if_absent(self, path: str, data: bytes) -> WebDavWriteResult:
        response = self._request(path, "PUT", data, {"If-None-Match": "*"})
        return WebDavWriteResult(response.etag)

    def put_if_match(self, path: str, data: bytes, etag: str) -> WebDavWriteResult:
        if not etag:
            raise ConditionalWriteUnsupported(f"{path} has no strong ETag for If-Match")
        response = self._request(path, "PUT", data, {"If-Match": etag})
        return WebDavWriteResult(response.etag)

    def delete_if_match(self, path: str, etag: str) -> None:
        if not etag:
            raise ConditionalWriteUnsupported(f"{path} has no strong ETag for If-Match")
        self._request(path, "DELETE", headers={"If-Match": etag})

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

    def _read_existing_remote(
        self,
        target_epub_path: str,
        manifest_path: str,
        initial_target: WebDavResource,
        initial_manifest: WebDavResource,
        expected_old_epub_hash: str | None,
        expected_old_manifest_hash: str | None,
    ) -> _ExistingRemote | str:
        if not initial_manifest.exists:
            return "existing target has no Hermes manifest"
        if expected_old_epub_hash is None or expected_old_manifest_hash is None:
            return "existing target overwrite requires expected old remote hashes"
        if not initial_target.etag or not initial_manifest.etag:
            return "existing target or manifest lacks a strong ETag for conditional overwrite"

        try:
            old_manifest_bytes = self.client.get(manifest_path)
            old_epub_bytes = self.client.get(target_epub_path)
            final_target = self.client.stat(target_epub_path)
            final_manifest = self.client.stat(manifest_path)
        except Exception:
            return "existing target or manifest unreadable"

        if (
            not final_target.exists
            or not final_manifest.exists
            or final_target.etag != initial_target.etag
            or final_manifest.etag != initial_manifest.etag
        ):
            return "existing target changed while preparing conditional publish"

        current_epub_hash = hashlib.sha256(old_epub_bytes).hexdigest()
        current_manifest_hash = hashlib.sha256(old_manifest_bytes).hexdigest()
        if (
            current_epub_hash != expected_old_epub_hash
            or current_manifest_hash != expected_old_manifest_hash
        ):
            return "existing target changed since update diff"

        return _ExistingRemote(
            old_epub_bytes,
            old_manifest_bytes,
            final_target.etag,
            final_manifest.etag,
        )

    def _write_backup(self, target_epub_path: str, slug: str, existing: _ExistingRemote) -> str | None:
        backup_root = posixpath.join(posixpath.dirname(target_epub_path), ".backups", slug)
        timestamp = self.timestamp()
        for suffix in range(1, 100):
            backup_name = timestamp if suffix == 1 else f"{timestamp}-{suffix}"
            backup_dir = posixpath.join(backup_root, backup_name)
            self.client.mkdir(backup_dir)
            try:
                self.client.put_if_absent(posixpath.join(backup_dir, "old.epub"), existing.epub_bytes)
                self.client.put_if_absent(
                    posixpath.join(backup_dir, "old.hermes.json"),
                    existing.manifest_bytes,
                )
                return None
            except ConditionalWriteFailed:
                continue
            except ConditionalWriteUnsupported:
                return "backup write could not be made conditionally"
        return "could not reserve a unique backup path"

    def _safe_put_if_match(self, path: str, data: bytes, etag: str | None) -> bool:
        if not etag:
            return False
        try:
            self.client.put_if_match(path, data, etag)
            return True
        except (ConditionalWriteFailed, ConditionalWriteUnsupported):
            return False

    def _safe_delete_if_match(self, path: str, etag: str | None) -> bool:
        if not etag:
            return False
        try:
            self.client.delete_if_match(path, etag)
            return True
        except (ConditionalWriteFailed, ConditionalWriteUnsupported):
            return False

    def _supports_existing_overwrite(self) -> bool:
        return bool(getattr(self.client, "supports_existing_overwrite", False))

    def _existing_overwrite_capability_error(self, target_epub_path: str) -> str | None:
        if isinstance(self.client, LocalWebDavClient):
            return None

        probe_dir = posixpath.join(posixpath.dirname(target_epub_path), ".hermes-capabilities")
        probe_path = posixpath.join(probe_dir, f"{uuid.uuid4().hex}.probe")
        try:
            self.client.mkdir(probe_dir)
            first = self.client.put_if_absent(probe_path, b"probe-1")
            if not first.etag:
                return "existing target overwrite requires WebDAV PUT response ETags"
            try:
                duplicate = self.client.put_if_absent(probe_path, b"probe-duplicate")
            except ConditionalWriteFailed:
                pass
            except ConditionalWriteUnsupported:
                return "existing target overwrite requires WebDAV If-None-Match support"
            else:
                self._safe_delete_if_match(probe_path, duplicate.etag)
                return "existing target overwrite requires WebDAV If-None-Match enforcement"
            try:
                stale = self.client.put_if_match(probe_path, b"probe-stale", '"hermes-stale-probe"')
            except ConditionalWriteFailed:
                pass
            except ConditionalWriteUnsupported:
                return "existing target overwrite requires WebDAV If-Match support"
            else:
                self._safe_delete_if_match(probe_path, stale.etag)
                return "existing target overwrite requires WebDAV If-Match enforcement"
            second = self.client.put_if_match(probe_path, b"probe-2", first.etag)
            if not second.etag:
                return "existing target overwrite requires WebDAV PUT response ETags"
            verified = self._verified_etag_after_write(probe_path, b"probe-2", second)
            if not verified:
                return "existing target overwrite probe could not be verified"
            self._safe_delete_if_match(probe_path, verified)
            return None
        except Exception:
            return "existing target overwrite probe failed"

    def _supports_new_publish(self) -> bool:
        return bool(getattr(self.client, "supports_new_publish", False))

    def _new_publish_capability_error(self, target_epub_path: str) -> str | None:
        if isinstance(self.client, LocalWebDavClient):
            return None

        probe_dir = posixpath.join(posixpath.dirname(target_epub_path), ".hermes-capabilities")
        probe_path = posixpath.join(probe_dir, f"{uuid.uuid4().hex}.probe")
        try:
            self.client.mkdir(probe_dir)
            first = self.client.put_if_absent(probe_path, b"probe-1")
            if not first.etag:
                return "new target publish requires WebDAV PUT response ETags"
            if not self._verified_after_write(probe_path, b"probe-1", first, require_etag=False):
                return "new target publish probe could not be verified"
            try:
                second = self.client.put_if_absent(probe_path, b"probe-2")
            except ConditionalWriteFailed:
                pass
            except ConditionalWriteUnsupported:
                return "new target publish requires WebDAV If-None-Match support"
            else:
                self._safe_delete_if_match(probe_path, second.etag)
                return "new target publish requires WebDAV If-None-Match enforcement"
            self._safe_delete_if_match(probe_path, first.etag)
            return None
        except Exception:
            return "new target publish probe failed"

    def _verified_after_write(
        self,
        path: str,
        expected_data: bytes,
        write_result: WebDavWriteResult,
        *,
        require_etag: bool = True,
    ) -> str | None:
        try:
            state = self.client.stat(path)
        except Exception:
            return None
        if write_result.etag:
            return write_result.etag if state.exists and state.etag == write_result.etag else None

        if not state.exists or (require_etag and not state.etag):
            return None
        try:
            current_data = self.client.get(path)
        except Exception:
            return None
        if hashlib.sha256(current_data).hexdigest() != hashlib.sha256(expected_data).hexdigest():
            return None
        if require_etag and not state.etag:
            return None
        return state.etag or ""

    def _verified_etag_after_write(
        self,
        path: str,
        expected_data: bytes,
        write_result: WebDavWriteResult,
    ) -> str | None:
        return self._verified_after_write(path, expected_data, write_result, require_etag=True)

    def _restore_existing_resource_after_failed_write(
        self,
        path: str,
        candidate_bytes: bytes,
        old_bytes: bytes,
        write_result: WebDavWriteResult | None,
    ) -> None:
        try:
            state = self.client.stat(path)
            current_bytes = self.client.get(path) if state.exists else b""
        except Exception:
            state = WebDavResource(False)
            current_bytes = b""

        if (
            state.exists
            and state.etag
            and hashlib.sha256(current_bytes).hexdigest() == hashlib.sha256(candidate_bytes).hexdigest()
        ):
            if self._safe_put_if_match(path, old_bytes, state.etag):
                return

        self._safe_put_if_match(
            path,
            old_bytes,
            write_result.etag if write_result else None,
        )

    def _publish_new_book(
        self,
        target_epub_path: str,
        manifest_path: str,
        epub_path: Path,
        manifest: BookManifest,
        decision_value: str,
    ) -> dict[str, str]:
        candidate_epub = epub_path.read_bytes()
        candidate_manifest = manifest.to_json().encode("utf-8")

        manifest_write: WebDavWriteResult | None = None
        try:
            manifest_write = self.client.put_if_absent(manifest_path, candidate_manifest)
        except ConditionalWriteFailed:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "manifest was created concurrently during conditional publish",
            )
        except ConditionalWriteUnsupported:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new manifest could not be created conditionally",
            )
        except Exception:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new manifest write failed before target creation",
            )

        manifest_write_etag = self._verified_after_write(
            manifest_path,
            candidate_manifest,
            manifest_write,
            require_etag=False,
        )
        if manifest_write_etag is None:
            self._safe_delete_if_match(manifest_path, manifest_write.etag if manifest_write else None)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new manifest write could not be verified before target publish",
            )

        target_write: WebDavWriteResult | None = None
        try:
            target_write = self.client.put_if_absent(target_epub_path, candidate_epub)
        except ConditionalWriteFailed:
            self._safe_delete_if_match(manifest_path, manifest_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "target was created concurrently during conditional publish",
            )
        except ConditionalWriteUnsupported:
            self._safe_delete_if_match(manifest_path, manifest_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new target could not be created conditionally",
            )
        except Exception:
            self._safe_delete_if_match(manifest_path, manifest_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new target write failed after manifest creation",
            )

        target_write_etag = self._verified_after_write(
            target_epub_path,
            candidate_epub,
            target_write,
            require_etag=False,
        )
        if target_write_etag is None:
            self._safe_delete_if_match(target_epub_path, target_write.etag if target_write else None)
            self._safe_delete_if_match(manifest_path, manifest_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new target write could not be verified after manifest publish",
            )

        if target_write_etag and manifest_write_etag:
            final_target = self.client.stat(target_epub_path)
            final_manifest = self.client.stat(manifest_path)
            if final_target.etag != target_write_etag or final_manifest.etag != manifest_write_etag:
                self._safe_delete_if_match(target_epub_path, target_write_etag)
                self._safe_delete_if_match(manifest_path, manifest_write_etag)
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "new target changed before publish verification completed",
                )
        return {"status": "published", "path": target_epub_path}

    def _publish_existing_book(
        self,
        target_epub_path: str,
        manifest_path: str,
        epub_path: Path,
        manifest: BookManifest,
        decision_value: str,
        existing: _ExistingRemote,
    ) -> dict[str, str]:
        if not self._supports_existing_overwrite():
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing target overwrite requires transactional WebDAV support",
            )

        candidate_epub = epub_path.read_bytes()
        candidate_manifest = manifest.to_json().encode("utf-8")
        target_write: WebDavWriteResult | None = None
        try:
            target_write = self.client.put_if_match(
                target_epub_path,
                candidate_epub,
                existing.epub_etag,
            )
        except ConditionalWriteFailed:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing target changed during conditional publish",
            )
        except ConditionalWriteUnsupported:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing target could not be overwritten conditionally",
            )

        target_write_etag = self._verified_etag_after_write(
            target_epub_path,
            candidate_epub,
            target_write,
        )
        if not target_write_etag:
            self._restore_existing_resource_after_failed_write(
                target_epub_path,
                candidate_epub,
                existing.epub_bytes,
                target_write,
            )
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing target write could not be verified after conditional publish",
            )

        manifest_write: WebDavWriteResult | None = None
        try:
            manifest_write = self.client.put_if_match(
                manifest_path,
                candidate_manifest,
                existing.manifest_etag,
            )
        except ConditionalWriteFailed:
            self._safe_put_if_match(
                target_epub_path,
                existing.epub_bytes,
                target_write_etag,
            )
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing manifest changed during conditional publish",
            )
        except ConditionalWriteUnsupported:
            self._safe_put_if_match(
                target_epub_path,
                existing.epub_bytes,
                target_write_etag,
            )
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing manifest could not be overwritten conditionally",
            )
        except Exception:
            self._safe_put_if_match(
                target_epub_path,
                existing.epub_bytes,
                target_write_etag,
            )
            raise

        manifest_write_etag = self._verified_etag_after_write(
            manifest_path,
            candidate_manifest,
            manifest_write,
        )
        if not manifest_write_etag:
            self._restore_existing_resource_after_failed_write(
                manifest_path,
                candidate_manifest,
                existing.manifest_bytes,
                manifest_write,
            )
            self._safe_put_if_match(target_epub_path, existing.epub_bytes, target_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing manifest write could not be verified after conditional publish",
            )

        final_target = self.client.stat(target_epub_path)
        final_manifest = self.client.stat(manifest_path)
        if final_target.etag != target_write_etag or final_manifest.etag != manifest_write_etag:
            self._safe_put_if_match(manifest_path, existing.manifest_bytes, manifest_write_etag)
            self._safe_put_if_match(target_epub_path, existing.epub_bytes, target_write_etag)
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "existing target changed before publish verification completed",
            )
        return {"status": "published", "path": target_epub_path}

    def _pending_update(
        self,
        target_epub_path: str,
        epub_path: Path,
        manifest: BookManifest,
        decision_value: str,
        reason: str | None = None,
    ) -> dict[str, str]:
        slug = Path(target_epub_path).stem
        candidate_epub = epub_path.read_bytes()
        candidate_manifest = manifest.to_json().encode("utf-8")
        candidate_hash = hashlib.sha256(candidate_epub).hexdigest()
        pending_root = posixpath.join(posixpath.dirname(target_epub_path), ".pending", slug)
        pending_name = f"{self.timestamp()}-{candidate_hash[:16]}"
        risk_report = (
            "# Pending update\n\n"
            f"Decision: {decision_value}\n"
            f"Candidate-SHA256: {candidate_hash}\n"
            + (f"Reason: {reason}\n" if reason else "")
        ).encode("utf-8")

        self.client.mkdir(pending_root)
        for suffix in range(1, 100):
            directory_name = pending_name if suffix == 1 else f"{pending_name}-{suffix}"
            pending_dir = posixpath.join(pending_root, directory_name)
            self.client.mkdir(pending_dir)
            try:
                self.client.put_if_absent(posixpath.join(pending_dir, "candidate.epub"), candidate_epub)
                self.client.put_if_absent(
                    posixpath.join(pending_dir, "candidate.hermes.json"),
                    candidate_manifest,
                )
                self.client.put_if_absent(posixpath.join(pending_dir, "risk-report.md"), risk_report)
                break
            except ConditionalWriteFailed:
                continue
        else:
            raise ConditionalWriteFailed("could not reserve a unique pending update path")

        report = {"status": "pending", "path": pending_dir, "candidate_hash": candidate_hash}
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

        try:
            target_state = self.client.stat(target_epub_path)
            manifest_state = self.client.stat(manifest_path)
        except Exception:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "remote target state unavailable",
            )

        if target_state.exists and decision_value not in safe_overwrite_decisions:
            return self._pending_update(target_epub_path, epub_path, manifest, decision_value)

        if target_state.exists:
            if not self._supports_existing_overwrite():
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    "existing target overwrite requires transactional WebDAV support",
                )
            capability_error = self._existing_overwrite_capability_error(target_epub_path)
            if capability_error is not None:
                return self._pending_update(
                    target_epub_path,
                    epub_path,
                    manifest,
                    decision_value,
                    capability_error,
                )
            existing = self._read_existing_remote(
                target_epub_path,
                manifest_path,
                target_state,
                manifest_state,
                expected_old_epub_hash,
                expected_old_manifest_hash,
            )
            if isinstance(existing, str):
                return self._pending_update(target_epub_path, epub_path, manifest, decision_value, existing)
            backup_error = self._write_backup(target_epub_path, slug, existing)
            if backup_error is not None:
                return self._pending_update(target_epub_path, epub_path, manifest, decision_value, backup_error)
            return self._publish_existing_book(
                target_epub_path,
                manifest_path,
                epub_path,
                manifest,
                decision_value,
                existing,
            )

        if manifest_state.exists:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "Hermes manifest exists without target EPUB",
            )

        if not self._supports_new_publish():
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                "new target publish requires verified conditional WebDAV support",
            )
        capability_error = self._new_publish_capability_error(target_epub_path)
        if capability_error is not None:
            return self._pending_update(
                target_epub_path,
                epub_path,
                manifest,
                decision_value,
                capability_error,
            )

        return self._publish_new_book(target_epub_path, manifest_path, epub_path, manifest, decision_value)
