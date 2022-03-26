import collections
import logging
import os
from pathlib import Path

from deluge_client import LocalDelugeRPCClient

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class Deluge:
    def __init__(self, username: str, password: str):
        self.client = LocalDelugeRPCClient(
            username=username,
            password=password,
        )
        self.client.connect()
        if not self.client.connected:
            raise ValueError()

    def torrent_dict(self) -> dict:
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
        torrents = self.torrent_dict()
        for _, torrent in torrents.items():
            list_torrents = sorted(torrent, key=lambda x: x["time_added"], reverse=True)
            if old_list_torrents := list_torrents[1:]:
                self.remove_old_files_in_new_torrent(list_torrents[0]["id"])
                for re_torrent in old_list_torrents:
                    self.client.call("core.remove_torrent", re_torrent["id"], {})

    @staticmethod
    def get_root_folder_torrent(base_folder, path):
        path = Path(path)
        if path.is_dir():
            pre_path = path
            while str(path) != base_folder:
                pre_path = path
                path = path.parent
            return pre_path

    def remove_old_files_in_new_torrent(self, torrent_id):
        torrent = self.client.call(
            "core.get_torrent_status", torrent_id, ["name", "save_path", "files"]
        )
        current_files = [
            os.path.join(torrent["save_path"], file["path"])
            for file in torrent["files"]
        ]
        folder = self.get_root_folder_torrent(
            torrent["save_path"], Path(current_files[0]).parent
        )
        if str(folder) != torrent["save_path"]:
            logging.info(f"Look in {folder}")
            remove_files = []
            for root, _, files in os.walk(folder):
                remove_files.extend(os.path.join(root, file) for file in files)
            for file in current_files:
                try:
                    remove_files.remove(file)
                except ValueError:
                    pass
            for file in remove_files:
                logging.info(f"Remove {file}")
                os.remove(file)

    def torrent_check(self):
        for key, torrent in self.client.call(
            "core.get_torrents_status", {}, ["name", "time_added"]
        ).items():
            logging.info(f"Check torrent: {torrent['name']}")
            self.remove_old_files_in_new_torrent(key)
