import collections
import logging
import posixpath

from qbittorrentapi import APIConnectionError, Client, LoginFailed

from .base_client import BaseTorrentClient

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class QBittorrent(BaseTorrentClient):
    def __init__(
        self,
        host: str = "localhost",
        port: int | None = 8080,
        username: str = "",
        password: str = "",
        verify_cert: bool = True,
    ):
        """
        Initializing work with qBittorrent.

        Initialize work with the qBittorrent client.

        :param host: qBittorrent host address or full URL (default: localhost).
        :param port: qBittorrent Web UI port (default: 8080). Set to None if host is full URL.
        :param username: qBittorrent Web UI username.
        :param password: qBittorrent Web UI password.
        :param verify_cert: Verify SSL certificate (default: True).
        """
        client_params = {
            "host": host,
            "username": username,
            "password": password,
            "VERIFY_WEBUI_CERTIFICATE": verify_cert,
        }

        if port is not None:
            client_params["port"] = port

        self.client = Client(**client_params)
        try:
            if not self.client.is_logged_in:
                self.client.auth_log_in()
        except LoginFailed as e:
            raise ValueError(f"Authentication failed: {e}")
        except APIConnectionError as e:
            raise ValueError(f"Failed to connect to qBittorrent: {e}")

    def torrent_dict(self) -> dict[str, list[dict]]:
        """
        Get the list of torrents.

        Returns a modified dictionary of torrents.

        :return: A dictionary of torrents where the key is the torrent name and the value is a list of
                 dictionaries with torrent information.
        """
        logging.info("Starting to get list of torrents")
        torrents = collections.defaultdict(list)

        for torrent in self.client.torrents_info():
            torrents[torrent.name].append({"id": torrent.hash, "name": torrent.name, "time_added": torrent.added_on})

        return dict(torrents)

    def get_torrent_info(self, torrent_id: str) -> dict:
        """
        Get information about a specific torrent.

        :param torrent_id: Torrent identifier (hash).
        :return: Dictionary with torrent information (name, save_path, files).
        """
        torrent = self.client.torrents_info(torrent_hashes=torrent_id)
        if not torrent:
            raise ValueError(f"Torrent with hash {torrent_id} not found")

        torrent = torrent[0]
        files = self.client.torrents_files(torrent_hash=torrent_id)

        # Convert file format to unified structure
        formatted_files = []
        for file in files:
            formatted_files.append({"path": file.name})

        return {"name": torrent.name, "save_path": torrent.save_path, "files": formatted_files}

    def remove_torrent(self, torrent_id: str):
        """
        Remove a torrent.

        :param torrent_id: Torrent identifier (hash).
        """
        self.client.torrents_delete(delete_files=False, torrent_hashes=torrent_id)
        logging.info(f"Removed torrent with hash: {torrent_id}")

    def all_torrents_status(self) -> list[dict]:
        """
        Get completeness status for every torrent in ONE ``torrents_info()`` call.

        qBittorrent reports ``progress`` on a ``0.0``-``1.0`` scale. For most torrents ``content_path``
        is an exact footprint (single file or root folder), so ``content_paths`` is ``[content_path]``.
        A ROOTLESS multi-file torrent, though, reports ``content_path == save_path`` (the whole download
        dir) — that is NOT an exact footprint, and treating it as one would let the torrent over-claim
        every sibling under ``save_path``. The per-torrent file list needed to reconstruct the real
        top-level entries is unavailable within this single batched call, so such a record is reported
        with an UNKNOWN footprint (``content_paths=[]``) and handled by the fail-closed backstop.

        Completion requires BOTH ``amount_left == 0`` AND ``progress >= 1.0``: a magnet still
        fetching metadata reports ``amount_left == 0`` (wanted size unknown) at ``progress == 0``,
        and a rechecking torrent can show ``progress == 1.0`` with ``amount_left > 0`` — either alone
        would misclassify an unfinished torrent as done and let the gate certify COMPLETE over it.

        A partially-selected torrent (``size < total_size``) can report itself finished once its
        WANTED files complete while a deselected file stays partial. torrents_info() carries no
        per-file data, so for those (rare) finished-but-partial torrents ONLY, one extra
        ``torrents_files()`` call resolves the exact ``incomplete_paths``; fully-selected torrents
        keep the single-batched-call fast path.

        :return: One dict per torrent with ``id``/``name``/``save_path``/``content_path``/
                 ``content_paths``/``incomplete_paths``/``progress``/``is_finished``/``state``.
        """
        result = []
        for t in self.client.torrents_info():
            content_path = getattr(t, "content_path", None)
            save_path = t.save_path
            # Rootless multi-file torrent (content_path == save_path) -> footprint unknown, fail closed.
            if (
                content_path
                and save_path
                and BaseTorrentClient._canon(str(content_path)) == BaseTorrentClient._canon(str(save_path))
            ):
                content_path = None
            progress = float(getattr(t, "progress", 0) or 0)
            amount_left = getattr(t, "amount_left", None)
            is_finished = amount_left == 0 and progress >= 1.0
            result.append(
                {
                    "id": t.hash,
                    "name": t.name,
                    "save_path": save_path,
                    "content_path": content_path,
                    "content_paths": [content_path] if content_path else [],
                    "incomplete_paths": self._incomplete_paths(t, save_path, is_finished),
                    "progress": progress,
                    "is_finished": is_finished,
                    "state": getattr(t, "state", None),
                }
            )
        return result

    def _incomplete_paths(self, t, save_path, is_finished: bool) -> list[str]:
        """Exact paths of not-fully-downloaded files for a FINISHED-looking torrent, or ``[]``.

        Only a finished torrent whose selected size is smaller than its total size can be hiding a
        partial deselected file; everything else is either genuinely done or already handled by the
        coarse ``is_finished`` gate, so no per-file call is made. On a finished-but-partial torrent
        we resolve the real partial files via ``torrents_files()``. Because such a torrent MUST have
        files, an exception OR an empty response means the lookup failed (e.g. the torrent vanished
        between the batch and per-file calls); either way we fail closed by marking the whole known
        extent incomplete rather than certifying blindly.
        """
        if not is_finished or not save_path:
            return []
        size = getattr(t, "size", None)
        total = getattr(t, "total_size", None)
        if not (isinstance(size, int) and isinstance(total, int) and size < total):
            return []  # fully selected (or size unknown) -> is_finished is already trustworthy
        try:
            files = self.client.torrents_files(torrent_hash=t.hash)
        except Exception:
            files = None
        if not files:  # exception or empty response for a torrent that must have files -> fail closed
            fallback = getattr(t, "content_path", None) or save_path
            return [BaseTorrentClient._canon(str(fallback))]
        out = []
        for f in files:
            if float(getattr(f, "progress", 0) or 0) < 1.0:
                name = getattr(f, "name", None)
                if name:
                    out.append(BaseTorrentClient._canon(posixpath.join(str(save_path), str(name))))
        return out
