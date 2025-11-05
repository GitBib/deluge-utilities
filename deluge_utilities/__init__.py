"""
:authors: GitBib
:license: Apache License, Version 2.0, see LICENSE file
:copyright: (c) 2022 GitBib
"""

from importlib.metadata import PackageNotFoundError, version

from .base_client import BaseTorrentClient
from .deluge import Deluge
from .qbittorrent import QBittorrent

try:
    __version__ = version("deluge-utilities")
except PackageNotFoundError:
    # Package is not installed, fallback for development
    __version__ = "0.0.5-dev"

__author__ = "GitBib"
__email__ = "job@bnff.website"

__all__ = ["BaseTorrentClient", "Deluge", "QBittorrent"]
