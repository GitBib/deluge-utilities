"""Smoke test proving the pytest harness runs and the package exports its clients."""

import deluge_utilities
from deluge_utilities import BaseTorrentClient, Deluge, QBittorrent


def test_package_exports_clients():
    assert deluge_utilities.BaseTorrentClient is BaseTorrentClient
    assert deluge_utilities.Deluge is Deluge
    assert deluge_utilities.QBittorrent is QBittorrent


def test_all_declares_public_api():
    assert set(deluge_utilities.__all__) == {
        "BaseTorrentClient",
        "Deluge",
        "QBittorrent",
        "GateDecision",
        "decide",
    }
