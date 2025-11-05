import collections
import logging

from deluge_client import LocalDelugeRPCClient

from .base_client import BaseTorrentClient

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


class Deluge(BaseTorrentClient):
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
