# deluge-utilities

A set of utilities to help you work with Deluge and qBittorrent torrent clients.

## Features

- Unified interface for both Deluge and qBittorrent clients
- Automatic detection and removal of duplicate torrents
- Clean up extra files in torrent folders
- Search and remove old torrents while keeping the newest version
- Support for both local Deluge daemon and remote qBittorrent Web UI

## Installation

```bash
pip install deluge-utilities
```

For development:

```bash
git clone https://github.com/GitBib/deluge-utilities.git
cd deluge-utilities
uv sync
```

## Usage

### Deluge Client

```python
from deluge_utilities import Deluge

# Initialize Deluge client (connects to local daemon)
client = Deluge(
    username="your_deluge_username",
    password="your_deluge_password"
)

# Get list of all torrents grouped by name
torrents = client.torrent_dict()

# Search and remove old duplicate torrents, keeping only the newest
client.old_torrent_search()

# Check all torrents for extra files and remove them
client.torrent_check()

# Get information about a specific torrent
torrent_info = client.get_torrent_info("torrent_id")

# Remove a specific torrent
client.remove_torrent("torrent_id")
```

### qBittorrent Client

```python
from deluge_utilities import QBittorrent

# Initialize qBittorrent client (connects to Web UI)
client = QBittorrent(
    host="localhost",
    port=8080,
    username="your_qbittorrent_username",
    password="your_qbittorrent_password"
)

# Get list of all torrents grouped by name
torrents = client.torrent_dict()

# Search and remove old duplicate torrents, keeping only the newest
client.old_torrent_search()

# Check all torrents for extra files and remove them
client.torrent_check()

# Get information about a specific torrent
torrent_info = client.get_torrent_info("torrent_hash")

# Remove a specific torrent
client.remove_torrent("torrent_hash")
```

### Polymorphic Usage

Both clients implement the same interface, allowing you to switch between them easily:

```python
from deluge_utilities import Deluge, QBittorrent

# Choose client based on configuration
client_type = "qbittorrent"  # or "deluge"

if client_type == "deluge":
    client = Deluge(username="admin", password="password")
else:
    client = QBittorrent(
        host="localhost",
        port=8080,
        username="admin",
        password="password"
    )

# Use the same methods regardless of client type
torrents = client.torrent_dict()
client.old_torrent_search()
client.torrent_check()
```
