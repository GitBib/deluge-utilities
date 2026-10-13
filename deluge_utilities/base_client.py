import contextlib
import logging
import posixpath
from abc import ABC, abstractmethod
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class BaseTorrentClient(ABC):
    """Base abstract class for torrent clients."""

    @abstractmethod
    def torrent_dict(self) -> dict[str, list[dict]]:
        """
        Get the list of torrents.

        Returns a modified dictionary of torrents.

        :return: A dictionary of torrents where the key is the torrent name and the value is a list of
                 dictionaries with torrent information.
        """
        pass

    @abstractmethod
    def get_torrent_info(self, torrent_id: str) -> dict:
        """
        Get information about a specific torrent.

        :param torrent_id: Torrent identifier.
        :return: Dictionary with torrent information (name, save_path, files).
        """
        pass

    @abstractmethod
    def remove_torrent(self, torrent_id: str):
        """
        Remove a torrent.

        :param torrent_id: Torrent identifier.
        """
        pass

    def all_torrents_status(self) -> list[dict]:
        """
        Get completeness status for every torrent.

        Clients should batch the torrent listing when possible, but may need additional per-file
        calls to establish an exact footprint.

        :return: A list of dicts, one per torrent, each with keys: ``id``, ``name``,
                 ``save_path``, ``content_path`` (single on-disk file/folder path, or ``None``
                 when a torrent has several top-level entries), ``content_paths`` (the torrent's
                 EXACT top-level footprint as a list of absolute paths — one entry per top-level
                 file/dir; may be empty when the footprint is unknown), ``incomplete_paths``
                 (absolute paths of individual files that are NOT fully downloaded — including
                 deselected/skipped files that are partially present — so a directory query is not
                 certified COMPLETE while it still contains partial data), ``progress`` normalized
                 to ``0.0``-``1.0``, ``is_finished`` (bool), and ``state`` (str).
        """
        raise NotImplementedError

    @staticmethod
    def is_torrent_complete(status: dict) -> bool:
        """
        Whether a status record from :meth:`all_torrents_status` is fully downloaded.

        The client-derived ``is_finished`` flag is AUTHORITATIVE when present: an explicit
        ``False`` means not-done and must never be overridden by ``progress`` (a checking/rechecking
        torrent can transiently report ``progress == 1.0`` while data is still missing — trusting it
        would let a caller delete incomplete data). ``progress >= 1.0`` is used ONLY as a fallback
        when ``is_finished`` is absent/``None``. Do not branch on ``state`` strings — a
        complete-but-paused/queued torrent already reports ``is_finished`` True.

        :param status: One record from :meth:`all_torrents_status`.
        :return: True if the torrent is complete.
        """
        is_finished = status.get("is_finished")
        if is_finished is not None:
            return bool(is_finished)
        return float(status.get("progress") or 0) >= 1.0

    @staticmethod
    def _canon(path: str) -> str:
        """Lexically canonicalize a POSIX path: normalize ``.``/``..``/trailing slashes and
        collapse a leading ``//`` (which ``posixpath.normpath`` preserves) to a single ``/``."""
        p = posixpath.normpath(str(path))
        if p.startswith("//") and not p.startswith("///"):
            p = p[1:]
        return p

    @staticmethod
    def _resolve_query(path: str, remote_prefix: str | None, local_prefix: str | None) -> str:
        """Canonicalize ``path`` and map it into the client's reported domain.

        Normalizes ``.``/``..``/``//``/trailing slashes (defeats a lexical escape like
        ``/dl/complete/../incomplete``) and applies the ``local_prefix`` -> ``remote_prefix``
        translation ONLY when ``path`` is at or under ``local_prefix`` (component boundary —
        so ``/mnt/x-old`` is not treated as under ``/mnt/x``). Eligibility uses the root-aware
        :meth:`_contains`, so a ``local_prefix`` of ``/`` translates every absolute path (rather
        than silently no-op'ing on a ``//`` boundary test), and the suffix is re-rooted with
        ``posixpath.join`` so a root ``remote_prefix`` never fuses into ``/remoteShow``. Callers
        should pass a symlink-resolved path when symlinks are in play; normalization here is lexical.
        """
        query = BaseTorrentClient._canon(path)
        if remote_prefix and local_prefix:
            lp = BaseTorrentClient._canon(local_prefix)
            rp = BaseTorrentClient._canon(remote_prefix)
            if BaseTorrentClient._contains(lp, query):
                rel = query[len(lp) :].lstrip("/")
                query = BaseTorrentClient._canon(posixpath.join(rp, rel)) if rel else rp
        return query

    @staticmethod
    def _contains(base: str, other: str) -> bool:
        """Whether canonical ``base`` is ``other`` or an ancestor directory of it (root-aware)."""
        if base == "/":
            return other == "/" or other.startswith("/")
        return other == base or other.startswith(base + "/")

    @staticmethod
    def _owns(query: str, content_path: str | None) -> bool:
        """Whether ``content_path`` is ``query`` or an ancestor directory of it (boundary-safe)."""
        if not content_path:
            return False
        return BaseTorrentClient._contains(BaseTorrentClient._canon(content_path), query)

    @staticmethod
    def _overlaps(query: str, content_path: str | None) -> bool:
        """Whether the torrent's data and ``query`` overlap in EITHER direction.

        True when ``content_path`` contains ``query`` (the torrent backs the queried path) OR
        ``query`` contains ``content_path`` (the queried directory contains this torrent). The
        second direction is what stops a completed exact-parent from masking an incomplete child
        torrent nested inside a directory query.
        """
        if not content_path:
            return False
        base = BaseTorrentClient._canon(content_path)
        return BaseTorrentClient._contains(base, query) or BaseTorrentClient._contains(query, base)

    @staticmethod
    def _footprints(status: dict) -> list[str]:
        """A torrent's EXACT on-disk footprint as canonical absolute paths.

        Prefers the full ``content_paths`` list; falls back to ``[content_path]`` for records that
        only carry the single field. Only USABLE absolute paths survive — a ``None``, empty, or
        relative value is dropped, so a torrent whose real location cannot be established yields an
        empty list (and is then handled as unplaceable by :meth:`find_unmappable_incomplete`).
        """
        raw = status.get("content_paths")
        if not raw:
            cp = status.get("content_path")
            raw = [cp] if cp else []
        return [BaseTorrentClient._canon(str(p)) for p in raw if p and str(p).startswith("/")]

    @staticmethod
    def _overlaps_any(query: str, status: dict) -> bool:
        """Whether ANY of a torrent's footprint paths overlaps ``query`` in either direction."""
        return any(
            BaseTorrentClient._contains(fp, query) or BaseTorrentClient._contains(query, fp)
            for fp in BaseTorrentClient._footprints(status)
        )

    @staticmethod
    def find_owners_for_path(
        path: str,
        statuses: list[dict],
        *,
        remote_prefix: str | None = None,
        local_prefix: str | None = None,
    ) -> list[dict]:
        """
        All torrents whose ``content_path`` owns ``path``, most-specific (longest) first.

        Ownership is keyed ONLY on ``content_path``: a record without a ``content_path`` cannot
        establish ownership and is never returned (fail-closed — no ``save_path`` fallback, which
        would let one record claim every sibling under a shared save directory).

        :param path: Local filesystem path to resolve.
        :param statuses: Records from :meth:`all_torrents_status`.
        :param remote_prefix/local_prefix: Optional domain translation (see :meth:`_resolve_query`).
        :return: Owning records sorted longest-``content_path`` first (``[]`` if none).
        """
        query = BaseTorrentClient._resolve_query(path, remote_prefix, local_prefix)
        owners = [
            (len(BaseTorrentClient._canon(str(s["content_path"]))), s)
            for s in statuses
            if BaseTorrentClient._owns(query, s.get("content_path"))
        ]
        owners.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in owners]

    @staticmethod
    def find_overlapping_for_path(
        path: str,
        statuses: list[dict],
        *,
        remote_prefix: str | None = None,
        local_prefix: str | None = None,
    ) -> list[dict]:
        """
        All torrents whose data OVERLAPS ``path`` in either direction (ancestor OR descendant).

        Used by the completeness gate: a directory query must account both for the torrent that
        backs it AND for any torrent nested inside it, so a completed parent never hides an
        incomplete child. Matches on the torrent's EXACT footprint (:meth:`_footprints`), so a
        multi-root torrent is placed precisely by each of its top-level entries.
        """
        query = BaseTorrentClient._resolve_query(path, remote_prefix, local_prefix)
        return [s for s in statuses if BaseTorrentClient._overlaps_any(query, s)]

    @staticmethod
    def find_unmappable_incomplete(
        path: str,
        statuses: list[dict],
        *,
        remote_prefix: str | None = None,
        local_prefix: str | None = None,
    ) -> list[dict]:
        """
        Incomplete records the gate CANNOT place precisely, yet cannot rule out from overlapping the
        query — so certifying COMPLETE over them would be unsafe.

        A record with a usable footprint is handled precisely by :meth:`find_overlapping_for_path`
        and never appears here. This backstop covers records whose exact footprint is UNKNOWN
        (:meth:`_footprints` empty — e.g. an ambiguous multi-root torrent Deluge could not
        reconstruct, or metadata-only torrents), which are otherwise invisible to the overlap check
        and could be masked by a completed sibling:

        * usable ``save_path`` -> block only when that ``save_path`` overlaps the query (coarse: the
          data lives somewhere under it, but we don't know exactly where);
        * no usable ``save_path`` either -> globally unplaceable, so it blocks EVERY managed query
          for this client (we cannot prove it is elsewhere).

        Complete records are excluded — a finished torrent is no threat to deletion safety.
        """
        query = BaseTorrentClient._resolve_query(path, remote_prefix, local_prefix)
        blockers = []
        for s in statuses:
            if BaseTorrentClient.is_torrent_complete(s):
                continue
            if BaseTorrentClient._footprints(s):
                continue  # precisely placed -> covered by find_overlapping_for_path
            save_path = s.get("save_path")
            if save_path and str(save_path).startswith("/"):
                if BaseTorrentClient._overlaps(query, save_path):
                    blockers.append(s)
            else:
                blockers.append(s)  # no usable footprint and no usable save_path -> unplaceable
        return blockers

    @staticmethod
    def find_incomplete_overlaps(
        path: str,
        statuses: list[dict],
        *,
        remote_prefix: str | None = None,
        local_prefix: str | None = None,
    ) -> list[dict]:
        """
        Records with an individual NOT-fully-downloaded file (``incomplete_paths``) overlapping the
        query — precise per-file backstop for partial-selection torrents.

        A torrent may report ``is_finished`` True because its WANTED files are complete, yet a
        deselected/skipped file under the same footprint is only partially present. Certifying a
        directory that still contains that partial file would authorize destroying it. A file-level
        query for a sibling that IS complete does not overlap the partial file and stays certifiable.
        """
        query = BaseTorrentClient._resolve_query(path, remote_prefix, local_prefix)
        out = []
        for s in statuses:
            for ip in s.get("incomplete_paths") or []:
                if ip and str(ip).startswith("/") and BaseTorrentClient._overlaps(query, str(ip)):
                    out.append(s)
                    break
        return out

    @staticmethod
    def find_status_for_path(
        path: str,
        statuses: list[dict],
        *,
        remote_prefix: str | None = None,
        local_prefix: str | None = None,
    ) -> dict | None:
        """
        The single MOST-SPECIFIC torrent owning ``path`` (longest ``content_path``), or ``None``.

        See :meth:`find_owners_for_path` — ownership is ``content_path``-only (no ``save_path``
        fallback). When a path is owned by several nested torrents, use
        :meth:`find_owners_for_path` and require ALL complete rather than trusting this single
        record.
        """
        owners = BaseTorrentClient.find_owners_for_path(
            path, statuses, remote_prefix=remote_prefix, local_prefix=local_prefix
        )
        return owners[0] if owners else None

    def old_torrent_search(self, dry_run: bool = True):
        """
        Search and delete old torrents.

        Removes similar torrents by name from the list, then checks the new torrent folder for files
        that are not in the torrent.

        :param dry_run: If True, only log what would be deleted.
        """
        torrents = self.torrent_dict()
        for torrent_list in torrents.values():
            sorted_torrents = sorted(torrent_list, key=lambda x: x["time_added"], reverse=True)
            if len(sorted_torrents) > 1:
                newest_torrent, *old_torrents = sorted_torrents
                self.remove_old_files_in_new_torrent(newest_torrent["id"], dry_run=dry_run)
                for old_torrent in old_torrents:
                    if dry_run:
                        logging.info(
                            f"[DRY RUN] Would remove old duplicate torrent: {old_torrent['name']} ({old_torrent['id']})"
                        )
                    else:
                        self.remove_torrent(old_torrent["id"])
        logging.info(f"Old torrent check and removal completed (dry_run={dry_run})")

    @staticmethod
    def get_root_folder_torrent(base_folder: str, path: Path) -> Path:
        """
        Gets the main torrent folder.

        There is no way to get the main torrent folder, then you need to find out.

        :param base_folder: Passing save_path from torrent.
        :param path: Passing the path of the current file.

        :return: main torrent folder.
        """
        path = Path(path)
        if path.is_dir():
            pre_path = path
            while str(path) != base_folder:
                pre_path = path
                path = path.parent
            return pre_path
        return None

    def remove_old_files_in_new_torrent(self, torrent_id: str, dry_run: bool = True):
        """
        Remove files from the folder that should not be in the torrent.

        If we find duplicate torrents, delete the oldest ones and check for extra files in the new one.

        :param torrent_id: Torrent id.
        :param dry_run: If True, only log what would be deleted.
        """
        torrent = self.get_torrent_info(torrent_id)
        current_files = [Path(torrent["save_path"]) / file["path"] for file in torrent["files"]]

        if not current_files:
            logging.warning(f"No files found for torrent {torrent_id}")
            return

        folder = self.get_root_folder_torrent(torrent["save_path"], Path(current_files[0]).parent)
        if folder is None or str(folder) == torrent["save_path"]:
            logging.warning(f"Unable to determine root folder for torrent {torrent_id}")
            return

        logging.info(f"Look in {folder} (dry_run={dry_run})")
        remove_files = [path for path in folder.rglob("*") if path.is_file()]
        for file in current_files:
            with contextlib.suppress(ValueError):
                remove_files.remove(file)
        for file in remove_files:
            if dry_run:
                logging.info(f"[DRY RUN] Would remove file: {file}")
            else:
                logging.info(f"Remove {file}")
                file.unlink()

    def torrent_check(self, dry_run: bool = True):
        """
        Check all torrents and remove old files.

        :param dry_run: If True, only log what would be deleted.
        """
        torrents = self.torrent_dict()
        for torrent_list in torrents.values():
            for torrent in torrent_list:
                logging.info(f"Check torrent: {torrent['name']} (dry_run={dry_run})")
                self.remove_old_files_in_new_torrent(torrent["id"], dry_run=dry_run)

    def get_all_active_files(self) -> set[Path]:
        """
        Get absolute paths of all files in all active torrents.

        :return: A set of Path objects.
        """
        active_files = set()
        torrents = self.torrent_dict()
        for torrent_list in torrents.values():
            for t in torrent_list:
                info = self.get_torrent_info(t["id"])
                save_path = Path(info["save_path"])
                for f in info["files"]:
                    active_files.add((save_path / f["path"]).resolve())
        return active_files

    def cleanup_orphaned_data(self, base_path: str, dry_run: bool = True):
        """
        Global cleanup of orphaned files and folders.

        Scans the base_path and removes any files or folders not associated with any active torrent.

        :param base_path: The directory to scan for orphaned data.
        :param dry_run: If True, only log what would be deleted.
        """
        logging.info(f"Starting global cleanup in {base_path} (dry_run={dry_run})")
        active_files = self.get_all_active_files()
        base_dir = Path(base_path).resolve()

        if not base_dir.exists() or not base_dir.is_dir():
            logging.error(f"Base path {base_path} does not exist or is not a directory")
            return

        for item in base_dir.rglob("*"):
            if item.is_file():
                if item.resolve() not in active_files:
                    if dry_run:
                        logging.info(f"[DRY RUN] Would remove orphaned file: {item}")
                    else:
                        logging.info(f"Removing orphaned file: {item}")
                        item.unlink()

        for item in sorted(base_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if item.is_dir():
                if not any(item.iterdir()):
                    if dry_run:
                        logging.info(f"[DRY RUN] Would remove empty directory: {item}")
                    else:
                        logging.info(f"Removing empty directory: {item}")
                        item.rmdir()

        logging.info(f"Global cleanup completed (dry_run={dry_run})")
