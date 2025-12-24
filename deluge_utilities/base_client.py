import contextlib
import logging
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

    def old_torrent_search(self):
        """
        Search and delete old torrents.

        Removes similar torrents by name from the list, then checks the new torrent folder for files
        that are not in the torrent.
        """
        torrents = self.torrent_dict()
        for torrent_list in torrents.values():
            sorted_torrents = sorted(torrent_list, key=lambda x: x["time_added"], reverse=True)
            if len(sorted_torrents) > 1:
                newest_torrent, *old_torrents = sorted_torrents
                self.remove_old_files_in_new_torrent(newest_torrent["id"])
                for old_torrent in old_torrents:
                    self.remove_torrent(old_torrent["id"])
        logging.info("Old torrent check and removal completed")

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

    def torrent_check(self):
        """Check all torrents and remove old files."""
        torrents = self.torrent_dict()
        for torrent_list in torrents.values():
            for torrent in torrent_list:
                logging.info(f"Check torrent: {torrent['name']}")
                self.remove_old_files_in_new_torrent(torrent["id"])

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

        # 1. Remove orphaned files
        for item in base_dir.rglob("*"):
            if item.is_file():
                if item.resolve() not in active_files:
                    if dry_run:
                        logging.info(f"[DRY RUN] Would remove orphaned file: {item}")
                    else:
                        logging.info(f"Removing orphaned file: {item}")
                        item.unlink()

        # 2. Remove empty directories (bottom-up)
        for item in sorted(base_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if item.is_dir():
                # Check if directory is empty
                if not any(item.iterdir()):
                    if dry_run:
                        logging.info(f"[DRY RUN] Would remove empty directory: {item}")
                    else:
                        logging.info(f"Removing empty directory: {item}")
                        item.rmdir()

        logging.info(f"Global cleanup completed (dry_run={dry_run})")
