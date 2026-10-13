"""Tests for Deluge.all_torrents_status (mocked RPC, no live daemon)."""

from deluge_utilities import Deluge


class FakeRPC:
    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method, args))
        return self.ret


def _deluge(ret):
    d = Deluge.__new__(Deluge)  # bypass __init__ (connects to a live daemon)
    d.client = FakeRPC(ret)
    return d


def _t(name="A", save_path="/dl", progress=100, is_finished=True, state="Seeding", files=None, file_progress=None):
    t = {
        "name": name,
        "save_path": save_path,
        "progress": progress,
        "is_finished": is_finished,
        "state": state,
        "files": files or [],
    }
    if file_progress is not None:
        t["file_progress"] = file_progress
    return t


def test_progress_normalized_and_fields_passed_through():
    d = _deluge(
        {
            "idA": _t(progress=100, is_finished=True, files=[{"path": "A/e1.mkv"}, {"path": "A/e2.mkv"}]),
            "idB": _t(
                progress=55, is_finished=False, state="Downloading", files=[{"path": "B/e1.mkv"}, {"path": "B/e2.mkv"}]
            ),
        }
    )
    by = {s["id"]: s for s in d.all_torrents_status()}
    assert by["idA"]["progress"] == 1.0 and by["idA"]["is_finished"] is True and by["idA"]["state"] == "Seeding"
    assert by["idB"]["progress"] == 0.55 and by["idB"]["is_finished"] is False


def test_single_batched_call():
    d = _deluge({})
    d.all_torrents_status()
    assert len(d.client.calls) == 1 and d.client.calls[0][0] == "core.get_torrents_status"


def test_multifile_common_top_is_folder_content_path():
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}])})
    assert d.all_torrents_status()[0]["content_path"] == "/dl/Show"


def test_single_file_content_path_is_exact():
    d = _deluge({"idA": _t(files=[{"path": "movie.mkv"}])})
    assert d.all_torrents_status()[0]["content_path"] == "/dl/movie.mkv"


def test_mixed_top_level_yields_none_content_path():
    # ambiguous: two top-level entries -> single content_path is None (no over-claim)...
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "extra.nfo"}])})
    assert d.all_torrents_status()[0]["content_path"] is None


def test_mixed_top_level_footprint_lists_every_top():
    # ...but the EXACT footprint lists each distinct top-level entry so the torrent is placed precisely
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}, {"path": "extra.nfo"}])})
    assert sorted(d.all_torrents_status()[0]["content_paths"]) == ["/dl/Show", "/dl/extra.nfo"]


def test_single_top_level_footprint_matches_content_path():
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}])})
    s = d.all_torrents_status()[0]
    assert s["content_paths"] == ["/dl/Show"] and s["content_path"] == "/dl/Show"


def test_unsafe_path_yields_empty_footprint():
    d = _deluge({"idA": _t(files=[{"path": "../escape/e1.mkv"}, {"path": "ok.mkv"}])})
    s = d.all_torrents_status()[0]
    assert s["content_paths"] == [] and s["content_path"] is None


def test_partial_file_recorded_as_incomplete_path():
    # is_finished True but a skipped file is only 25% downloaded -> exact partial file is flagged
    d = _deluge(
        {
            "idA": _t(
                is_finished=True, files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}], file_progress=[1.0, 0.25]
            )
        }
    )
    s = d.all_torrents_status()[0]
    assert s["content_paths"] == ["/dl/Show"]
    assert s["incomplete_paths"] == ["/dl/Show/e2.mkv"]


def test_all_files_complete_has_no_incomplete_paths():
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}], file_progress=[1.0, 1.0])})
    assert d.all_torrents_status()[0]["incomplete_paths"] == []


def test_empty_file_progress_is_inconsistent_and_fails_closed():
    # file_progress present but empty against a non-empty file list -> distrust -> every file flagged
    d = _deluge(
        {"idA": _t(is_finished=True, files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}], file_progress=[])}
    )
    assert d.all_torrents_status()[0]["incomplete_paths"] == ["/dl/Show/e1.mkv", "/dl/Show/e2.mkv"]


def test_misaligned_file_progress_fails_closed():
    # length mismatch (present but wrong length) -> every file flagged incomplete
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}], file_progress=[1.0])})
    assert d.all_torrents_status()[0]["incomplete_paths"] == ["/dl/Show/e1.mkv", "/dl/Show/e2.mkv"]


def test_absent_file_progress_uses_coarse_gate():
    # no file_progress at all (None) -> no per-file marking, coarse is_finished applies
    d = _deluge({"idA": _t(files=[{"path": "Show/e1.mkv"}, {"path": "Show/e2.mkv"}])})
    assert d.all_torrents_status()[0]["incomplete_paths"] == []


def test_empty_files_yields_none_content_path():
    d = _deluge({"idA": _t(progress=10, is_finished=False, files=[])})
    assert d.all_torrents_status()[0]["content_path"] is None


def test_dotdot_file_path_yields_none():
    # a torrent file path with '..' would resolve outside save_path -> refuse (None)
    d = _deluge({"idA": _t(files=[{"path": "../escape/e1.mkv"}, {"path": "../escape/e2.mkv"}])})
    assert d.all_torrents_status()[0]["content_path"] is None


def test_absolute_file_path_yields_none():
    d = _deluge({"idA": _t(files=[{"path": "/etc/passwd"}])})
    assert d.all_torrents_status()[0]["content_path"] is None


def test_shared_save_path_binds_query_to_right_torrent():
    d = _deluge(
        {
            "idA": _t(progress=100, is_finished=True, files=[{"path": "A/e1.mkv"}, {"path": "A/e2.mkv"}]),
            "idB": _t(progress=40, is_finished=False, files=[{"path": "B/e1.mkv"}, {"path": "B/e2.mkv"}]),
        }
    )
    statuses = d.all_torrents_status()
    hit = Deluge.find_status_for_path("/dl/B/e2.mkv", statuses)
    assert hit["id"] == "idB" and Deluge.is_torrent_complete(hit) is False


class FakeLocalClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.connected = False
        self.calls = []
        self.disconnect_calls = 0
        type(self).instances.append(self)

    def connect(self):
        self.connected = True

    def call(self, method, *args):
        self.calls.append((method, args))
        return {}

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


def _construct(monkeypatch, **kwargs):
    import deluge_utilities.deluge as deluge_module

    FakeLocalClient.instances = []
    monkeypatch.setattr(deluge_module, "LocalDelugeRPCClient", FakeLocalClient)
    return Deluge(**kwargs)


def test_constructor_defaults_to_local_daemon(monkeypatch):
    d = _construct(monkeypatch, username="user", password="secret")
    assert d.client.kwargs == {"host": "127.0.0.1", "port": 58846, "username": "user", "password": "secret"}
    assert d.client.connected is True
    assert d.client.calls == [("core.get_torrents_status", ({}, ["name"]))]


def test_positional_credentials_remain_compatible(monkeypatch):
    import deluge_utilities.deluge as deluge_module

    FakeLocalClient.instances = []
    monkeypatch.setattr(deluge_module, "LocalDelugeRPCClient", FakeLocalClient)
    d = Deluge("user", "secret")
    assert d.client.kwargs["username"] == "user" and d.client.kwargs["password"] == "secret"
    assert d.client.kwargs["host"] == "127.0.0.1" and d.client.kwargs["port"] == 58846


def test_constructor_passes_remote_host_and_port(monkeypatch):
    d = _construct(monkeypatch, username="user", password="secret", host="192.0.2.10", port=58900)
    assert d.client.kwargs["host"] == "192.0.2.10" and d.client.kwargs["port"] == 58900


def test_constructor_raises_when_not_connected(monkeypatch):
    import pytest

    import deluge_utilities.deluge as deluge_module

    class NeverConnects(FakeLocalClient):
        def connect(self):
            self.connected = False

    monkeypatch.setattr(deluge_module, "LocalDelugeRPCClient", NeverConnects)
    with pytest.raises(ValueError):
        Deluge(username="user", password="secret", host="192.0.2.10")
    assert NeverConnects.instances[-1].disconnect_calls == 1


def test_constructor_rejects_unauthorized_session_and_disconnects(monkeypatch):
    import pytest

    import deluge_utilities.deluge as deluge_module

    class Unauthorized(FakeLocalClient):
        def call(self, method, *args):
            raise PermissionError("not authorized")

    Unauthorized.instances = []
    monkeypatch.setattr(deluge_module, "LocalDelugeRPCClient", Unauthorized)
    with pytest.raises(ValueError, match="authorization check failed"):
        Deluge(username="user", password="wrong", host="192.0.2.10")
    client = Unauthorized.instances[-1]
    assert client.connected is False
    assert client.disconnect_calls == 1


def test_zero_size_file_is_not_incomplete():
    files = [{"path": "Show/empty.txt", "size": 0}, {"path": "Show/video.mkv", "size": 100}]
    content_paths, incomplete_paths = Deluge._footprint("/downloads", files, [0.0, 1.0])
    assert content_paths == ["/downloads/Show"]
    assert incomplete_paths == []


def test_unknown_or_invalid_size_remains_conservative():
    files = [{"path": "missing-size.txt"}, {"path": "invalid-size.txt", "size": "0"}]
    _, incomplete_paths = Deluge._footprint("/downloads", files, [0.0, 0.0])
    assert incomplete_paths == ["/downloads/missing-size.txt", "/downloads/invalid-size.txt"]
