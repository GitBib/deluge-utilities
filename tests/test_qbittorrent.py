"""Tests for QBittorrent.all_torrents_status (mocked client, no live WebUI)."""

from types import SimpleNamespace

import pytest

from deluge_utilities import QBittorrent


class FakeClient:
    def __init__(self, torrents, files_by_hash=None):
        self._torrents = torrents
        self._files_by_hash = files_by_hash or {}
        self.calls = 0
        self.files_calls = []

    def torrents_info(self, **kwargs):
        self.calls += 1
        return self._torrents

    def torrents_files(self, torrent_hash=None, **kwargs):
        self.files_calls.append(torrent_hash)
        return self._files_by_hash.get(torrent_hash, [])


def _qbt(torrents, files_by_hash=None):
    # Bypass __init__ (it logs in to a live WebUI); inject a fake client.
    q = QBittorrent.__new__(QBittorrent)
    q.client = FakeClient(torrents, files_by_hash)
    return q


def _t(
    h,
    name="n",
    save_path="/dl",
    content_path="/dl/n",
    progress=1.0,
    amount_left=0,
    state="uploading",
    size=None,
    total_size=None,
):
    return SimpleNamespace(
        hash=h,
        name=name,
        save_path=save_path,
        content_path=content_path,
        progress=progress,
        amount_left=amount_left,
        state=state,
        size=size,
        total_size=total_size,
    )


def test_complete_torrent_maps_to_finished():
    q = _qbt([_t("h1", progress=1.0, amount_left=0)])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is True
    assert s["progress"] == 1.0
    assert QBittorrent.is_torrent_complete(s) is True


def test_partial_torrent_not_finished():
    q = _qbt([_t("h2", progress=0.6, amount_left=1234)])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is False
    assert s["progress"] == 0.6
    assert QBittorrent.is_torrent_complete(s) is False


def test_content_path_passed_through_and_matchable():
    q = _qbt([_t("h3", content_path="/dl/Show", progress=1.0, amount_left=0)])
    statuses = q.all_torrents_status()
    hit = QBittorrent.find_status_for_path("/dl/Show/ep01.mkv", statuses)
    assert hit["id"] == "h3"


def test_single_batched_call():
    q = _qbt([_t("h1"), _t("h2")])
    q.all_torrents_status()
    assert q.client.calls == 1


def test_amount_left_none_is_not_finished():
    q = _qbt([_t("h4", progress=0.5, amount_left=None)])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is False
    assert QBittorrent.is_torrent_complete(s) is False


def test_amount_left_missing_attr_is_not_finished():
    # a torrent object lacking amount_left entirely must not read as finished
    t = SimpleNamespace(hash="h5", name="n", save_path="/dl", content_path="/dl/n", progress=0.7, state="downloading")
    q = _qbt([t])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is False
    assert QBittorrent.is_torrent_complete(s) is False


def test_metadata_fetching_torrent_not_finished():
    # a magnet still fetching metadata reports amount_left=0 at progress=0 -> must NOT read as finished
    t = SimpleNamespace(
        hash="h6", name="n", save_path="/dl", content_path="", progress=0.0, amount_left=0, state="metaDL"
    )
    q = _qbt([t])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is False
    assert s["content_paths"] == []
    assert QBittorrent.is_torrent_complete(s) is False


def test_rechecking_progress_one_but_data_left_not_finished():
    # amount_left>0 while progress momentarily 1.0 (recheck) must NOT read as finished
    t = SimpleNamespace(
        hash="h7", name="n", save_path="/dl", content_path="/dl/n", progress=1.0, amount_left=512, state="checkingDL"
    )
    q = _qbt([t])
    s = q.all_torrents_status()[0]
    assert s["is_finished"] is False
    assert QBittorrent.is_torrent_complete(s) is False


def test_rootless_multifile_footprint_is_unknown():
    # a rootless multi-file torrent reports content_path == save_path (the whole dir); that is not an
    # exact footprint, so it must be reported as unknown rather than over-claiming every sibling.
    t = _t("h8", save_path="/dl", content_path="/dl", progress=1.0, amount_left=0)
    q = _qbt([t])
    s = q.all_torrents_status()[0]
    assert s["content_path"] is None
    assert s["content_paths"] == []


def test_rootless_complete_torrent_does_not_own_unrelated_sibling():
    t = _t("h9", save_path="/dl", content_path="/dl", progress=1.0, amount_left=0)
    q = _qbt([t])
    statuses = q.all_torrents_status()
    # its footprint is unknown, so it must not be matched as the owner of an arbitrary sub-path
    assert QBittorrent.find_status_for_path("/dl/unrelated/partial.mkv", statuses) is None


def test_fully_selected_torrent_makes_no_extra_files_call():
    # size == total_size (or unknown) -> is_finished is trustworthy, no per-file lookup
    q = _qbt([_t("h1", size=100, total_size=100, progress=1.0, amount_left=0)])
    s = q.all_torrents_status()[0]
    assert s["incomplete_paths"] == []
    assert q.client.files_calls == [] and q.client.calls == 1


def test_partial_selection_finds_exact_incomplete_file():
    # a finished torrent with a deselected partial file -> one extra torrents_files() call resolves it
    t = _t("h1", save_path="/dl", content_path="/dl/Show", progress=1.0, amount_left=0, size=100, total_size=200)
    files = [SimpleNamespace(name="Show/e1.mkv", progress=1.0), SimpleNamespace(name="Show/e2.mkv", progress=0.25)]
    q = _qbt([t], files_by_hash={"h1": files})
    s = q.all_torrents_status()[0]
    assert s["incomplete_paths"] == ["/dl/Show/e2.mkv"]
    assert q.client.files_calls == ["h1"]


def test_partial_selection_files_lookup_failure_fails_closed():
    class Boom(FakeClient):
        def torrents_files(self, torrent_hash=None, **kwargs):
            raise RuntimeError("boom")

    t = _t("h1", save_path="/dl", content_path="/dl/Show", progress=1.0, amount_left=0, size=100, total_size=200)
    q = QBittorrent.__new__(QBittorrent)
    q.client = Boom([t])
    s = q.all_torrents_status()[0]
    # cannot confirm which files are partial -> mark the whole known extent incomplete
    assert s["incomplete_paths"] == ["/dl/Show"]


def test_partial_selection_empty_files_response_fails_closed():
    # torrents_files() returning [] (e.g. torrent vanished between calls) for a partial-selection
    # torrent must NOT read as fully complete -> fail closed to the whole known extent.
    t = _t("h1", save_path="/dl", content_path="/dl/Show", progress=1.0, amount_left=0, size=100, total_size=200)
    q = _qbt([t], files_by_hash={})  # no files for h1 -> empty response
    s = q.all_torrents_status()[0]
    assert s["incomplete_paths"] == ["/dl/Show"]


@pytest.mark.parametrize("already_authorized", [False, True])
def test_constructor_logs_in_only_when_required(monkeypatch, already_authorized):
    import deluge_utilities.qbittorrent as module

    class LoginClient:
        is_logged_in = already_authorized

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.login_calls = 0

        def auth_log_in(self):
            self.login_calls += 1

    monkeypatch.setattr(module, "Client", LoginClient)
    client = QBittorrent(host="http://localhost:8080", port=None, username="user", password="secret")
    assert client.client.login_calls == int(not already_authorized)
    assert "port" not in client.client.kwargs


def test_constructor_rejects_bad_credentials_when_authentication_required(monkeypatch):
    import deluge_utilities.qbittorrent as module

    class RejectedClient:
        is_logged_in = False

        def __init__(self, **kwargs):
            pass

        def auth_log_in(self):
            raise module.LoginFailed()

    monkeypatch.setattr(module, "Client", RejectedClient)
    with pytest.raises(ValueError, match="Authentication failed"):
        QBittorrent(username="user", password="wrong")
