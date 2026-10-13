import collections
import contextlib
import logging
import posixpath
from pathlib import PurePosixPath

from deluge_client import LocalDelugeRPCClient

from .base_client import BaseTorrentClient

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class Deluge(BaseTorrentClient):
    def __init__(self, username: str, password: str, host: str = "127.0.0.1", port: int = 58846):
        """
        Initializing work with deluge.

        Initialize work with a deluge daemon, local by default.

        :param username: Login from deluge worker.
        :param password: Password from deluge worker.
        :param host: Deluge daemon RPC host (default: 127.0.0.1).
        :param port: Deluge daemon RPC port (default: 58846).
        """
        self.client = LocalDelugeRPCClient(
            host=host,
            port=port,
            username=username,
            password=password,
        )
        try:
            self.client.connect()
            if not self.client.connected:
                raise ValueError("Failed to connect to Deluge")
            # Verify the authenticated session can perform the read operation this client requires.
            # deluge-client marks itself connected even when daemon.login returns False.
            self.client.call("core.get_torrents_status", {}, ["name"])
        except Exception as error:
            was_connected = self.client.connected
            with contextlib.suppress(Exception):
                self.client.disconnect()
            if was_connected:
                raise ValueError("Deluge authorization check failed") from error
            raise

    def torrent_dict(self) -> dict[str, list[dict]]:
        """
        Get the list of torrents.

        Returns a modified dictionary of torrents.

        :return: A dictionary of torrents where the key is the torrent name and the value is a list of
                 dictionaries with torrent information.
        """
        logging.info("Starting to get list of torrents")
        torrents = collections.defaultdict(list)
        for torrent_id, torrent_info in self.client.call(
            "core.get_torrents_status", {}, ("name", "time_added")
        ).items():
            torrents[torrent_info["name"]].append({"id": torrent_id, **torrent_info})
        return dict(torrents)

    def get_torrent_info(self, torrent_id: str) -> dict:
        """
        Get information about a specific torrent.

        :param torrent_id: Torrent identifier.
        :return: Dictionary with torrent information (name, save_path, files).
        """
        torrent_status = self.client.call("core.get_torrent_status", torrent_id, ["name", "save_path", "files"])

        # Convert file format to unified structure
        formatted_files = []
        for file in torrent_status.get("files", []):
            formatted_files.append({"path": file["path"]})

        return {"name": torrent_status["name"], "save_path": torrent_status["save_path"], "files": formatted_files}

    def remove_torrent(self, torrent_id: str):
        """
        Remove a torrent.

        :param torrent_id: Torrent identifier.
        """
        self.client.call("core.remove_torrent", torrent_id, {})

    @staticmethod
    def _footprint(save_path, files: list[dict], file_progress=None) -> tuple[list[str], list[str]]:
        """Reconstruct a torrent's EXACT footprint AND its not-yet-complete files.

        Returns ``(content_paths, incomplete_paths)``:

        * ``content_paths`` — one absolute path per DISTINCT top-level entry under ``save_path``
          (single-file torrent -> that file; single-folder -> that folder; multi-root -> every
          top-level file/dir, so it is placed precisely rather than collapsed away).
        * ``incomplete_paths`` — the exact absolute path of every file whose ``file_progress`` is
          below ``1.0`` (a partially-present file, INCLUDING deselected/skipped files that were once
          partially downloaded), so a directory query is never certified while such a file remains.

        Fail-closed to ``([], [])`` when the footprint cannot be trusted: no ``save_path``/no files,
        an unsafe torrent-reported path (absolute, or containing ``.``/``..`` — ``../x`` would escape
        ``save_path``), or a reconstructed path that would land outside ``save_path``. Per-file
        completion is trusted only when ``file_progress`` is PRESENT and ALIGNS with ``files`` (a list
        of the same length). When it is ABSENT (``None``), ``incomplete_paths`` is left empty and the
        coarse ``is_finished`` gate applies; when it is PRESENT but not an aligned list — wrong type,
        wrong length, or an empty ``[]`` against a non-empty file list — the data is inconsistent and
        every file is marked incomplete so the gate fails closed rather than treating unchecked files
        as complete.
        """
        if not save_path or not files:
            return [], []
        base = PurePosixPath(str(save_path))
        base_n = posixpath.normpath(str(base))
        present = file_progress is not None
        progress = file_progress if isinstance(file_progress, (list, tuple)) else []
        aligned = isinstance(file_progress, (list, tuple)) and len(progress) == len(files)
        inconsistent = present and not aligned  # present but not an aligned list ([] / wrong type/len)
        tops: dict[str, str] = {}
        incomplete: list[str] = []
        for i, f in enumerate(files):
            p = PurePosixPath(str(f["path"]))
            if p.is_absolute() or any(part in (".", "..") for part in p.parts) or not p.parts:
                return [], []  # unsafe path -> refuse the whole torrent (no partial/over-claim)
            cp = posixpath.normpath(str(base / p))
            if cp != base_n and not cp.startswith(base_n.rstrip("/") + "/"):
                return [], []  # reconstructed path escaped save_path
            top = p.parts[0]
            if top not in tops:
                tops[top] = posixpath.normpath(str(base / top))
            size = f.get("size")
            zero_size = not isinstance(size, bool) and isinstance(size, (int, float)) and size == 0
            if not zero_size and (inconsistent or (aligned and not Deluge._fully_done(progress[i]))):
                incomplete.append(cp)
        return list(tops.values()), incomplete

    @staticmethod
    def _fully_done(value) -> bool:
        """True only when a per-file progress value is a number >= 1.0; a non-numeric or missing
        value is treated as NOT done (fail closed) rather than assumed complete."""
        try:
            return float(value) >= 1.0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _content_paths(save_path, files: list[dict]) -> list[str]:
        """The torrent's exact top-level footprint (see :meth:`_footprint`)."""
        return Deluge._footprint(save_path, files)[0]

    @staticmethod
    def _content_path(save_path, files: list[dict]) -> str | None:
        """The single ``content_path`` when a torrent has exactly one top-level entry, else ``None``.

        Kept for the single-owner resolvers (:meth:`find_status_for_path`); the exact footprint used
        by the completeness gate is :meth:`_content_paths`.
        """
        paths = Deluge._content_paths(save_path, files)
        return paths[0] if len(paths) == 1 else None

    def all_torrents_status(self) -> list[dict]:
        """
        Get completeness status for every torrent in ONE RPC call.

        ``progress`` is normalized from Deluge's 0-100 scale to ``0.0``-``1.0``. The torrent's exact
        footprint (``content_paths``) is reconstructed from ``save_path`` + its top-level entries so
        paths bind to the specific torrent even when many torrents share one ``save_path`` (matching
        by ``save_path`` alone would be ambiguous). ``content_path`` is the single footprint entry
        when unambiguous, else ``None``. ``file_progress`` is requested in the SAME call to derive
        ``incomplete_paths`` (files below 100%, including deselected/skipped partial files), so the
        gate is not fooled by a torrent that reports ``is_finished`` while a skipped file is partial.

        :return: One dict per torrent with ``id``/``name``/``save_path``/``content_path``/
                 ``content_paths``/``incomplete_paths``/``progress``/``is_finished``/``state``.
        """
        raw = self.client.call(
            "core.get_torrents_status",
            {},
            ["name", "save_path", "progress", "is_finished", "state", "files", "file_progress"],
        )
        result = []
        for torrent_id, info in raw.items():
            save_path = info.get("save_path")
            files = info.get("files") or []
            content_paths, incomplete_paths = self._footprint(save_path, files, info.get("file_progress"))
            result.append(
                {
                    "id": torrent_id,
                    "name": info.get("name"),
                    "save_path": save_path,
                    "content_path": content_paths[0] if len(content_paths) == 1 else None,
                    "content_paths": content_paths,
                    "incomplete_paths": incomplete_paths,
                    "progress": float(info.get("progress") or 0) / 100.0,
                    "is_finished": bool(info.get("is_finished")),
                    "state": info.get("state"),
                }
            )
        return result
