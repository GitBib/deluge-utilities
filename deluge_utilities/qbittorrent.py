import collections
import logging

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
