import collections
import contextlib
import logging
from deluge_client import LocalDelugeRPCClient
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class Deluge:
    def __init__(self, username: str, password: str):
        """
        Initializing work with deluge.

        Initialize work with the local deluge worker.

        :param username: Login from deluge worker.
        :param password: Password from deluge worker.
        """
        self.client = LocalDelugeRPCClient(
            username=username,
            password=password,
        )
        self.client.connect()
        if not self.client.connected:
            raise ValueError()

    def torrent_dict(self) -> dict:
        """
        Getting the torrent list.

        We get a modified torrent dictionary.

        :return: dict torrents.
        """
        logging.info("Start get list torrents")
        torrents = collections.defaultdict(list)
        for key, torrent in self.client.call(
            "core.get_torrents_status", {}, ["name", "time_added"]
        ).items():
            torrents[torrent["name"]].append(
                dict(
                    id=key,
                    **torrent,
                )
            )
        return torrents

    def old_torrent_search(self):
        """
        Search and delete old torrents.

        Delete similar torrents by name from the list, and then look in the new torrent folder for files that are not
        in the torrent.
        """
        torrents = self.torrent_dict()
        for _, torrent in torrents.items():
            list_torrents = sorted(torrent, key=lambda x: x["time_added"], reverse=True)
            if old_list_torrents := list_torrents[1:]:
                self.remove_old_files_in_new_torrent(list_torrents[0]["id"])
                for re_torrent in old_list_torrents:
                    self.client.call("core.remove_torrent", re_torrent["id"], {})

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

    def remove_old_files_in_new_torrent(self, torrent_id: str):
        """
        Remove files from the folder that should not be in the torrent.

        If we find duplicate torrents, delete the oldest ones and check for extra files in the new one.

        :param torrent_id: Torrent id deluge.
        """
        torrent = self.client.call(
            "core.get_torrent_status", torrent_id, ["name", "save_path", "files"]
        )
        current_files = [
            Path(torrent["save_path"]) / file["path"]
            for file in torrent["files"]
        ]
        folder = self.get_root_folder_torrent(
            torrent["save_path"], Path(current_files[0]).parent
        )
        if folder is None or str(folder) == torrent["save_path"]:
            logging.warning(f"Unable to determine root folder for torrent {torrent_id}")
            return

        logging.info(f"Look in {folder}")
        remove_files = [path for path in folder.rglob('*') if path.is_file()]
        for file in current_files:
            with contextlib.suppress(ValueError):
                remove_files.remove(file)
        for file in remove_files:
            logging.info(f"Remove {file}")
            file.unlink()

    def torrent_check(self):
        for key, torrent in self.client.call(
            "core.get_torrents_status", {}, ["name", "time_added"]
        ).items():
            logging.info(f"Check torrent: {torrent['name']}")
            self.remove_old_files_in_new_torrent(key)
