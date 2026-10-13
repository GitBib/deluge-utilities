"""Tests for the completeness helpers on BaseTorrentClient."""

from deluge_utilities import BaseTorrentClient

complete = BaseTorrentClient.is_torrent_complete
find = BaseTorrentClient.find_status_for_path
owners = BaseTorrentClient.find_owners_for_path


def test_legacy_subclass_without_status_api_remains_instantiable():
    class LegacyClient(BaseTorrentClient):
        def torrent_dict(self):
            return {}

        def get_torrent_info(self, torrent_id):
            return {}

        def remove_torrent(self, torrent_id):
            return None

    client = LegacyClient()

    import pytest

    with pytest.raises(NotImplementedError):
        client.all_torrents_status()


def test_complete_when_is_finished():
    assert complete({"is_finished": True, "progress": 0.4}) is True


def test_explicit_not_finished_is_authoritative():
    # is_finished=False is authoritative: progress=1.0 (e.g. transient recheck) must NOT override it
    assert complete({"is_finished": False, "progress": 1.0}) is False


def test_progress_fallback_only_when_is_finished_missing():
    # with no is_finished flag at all, fall back to progress
    assert complete({"progress": 1.0}) is True
    assert complete({"progress": 0.5}) is False


def test_incomplete_when_partial():
    assert complete({"is_finished": False, "progress": 0.99}) is False


def test_incomplete_when_fields_missing():
    assert complete({}) is False


def _st(name, content_path=None, save_path=None, **extra):
    return {"id": name, "name": name, "content_path": content_path, "save_path": save_path, **extra}


def test_matches_by_content_path_exact():
    a, b = _st("a", content_path="/dl/A"), _st("b", content_path="/dl/B")
    assert find("/dl/A", [a, b]) is a


def test_matches_by_content_path_prefix():
    a = _st("a", content_path="/dl/A")
    assert find("/dl/A/ep01.mkv", [a]) is a


def test_returns_none_when_unowned():
    a = _st("a", content_path="/dl/A")
    assert find("/somewhere/else", [a]) is None


def test_no_save_path_fallback_ownership():
    # A record without content_path can NEVER own a path (fail-closed).
    a = _st("a", content_path=None, save_path="/dl/only")
    assert find("/dl/only/x.mkv", [a]) is None
    assert owners("/dl/only/x.mkv", [a]) == []


def test_most_specific_owner_wins_over_parent():
    parent = _st("parent", content_path="/dl/Show")
    child = _st("child", content_path="/dl/Show/ep.mkv")
    # both "own" the exact file, but the more specific child is the true owner
    assert find("/dl/Show/ep.mkv", [parent, child]) is child
    assert [o["id"] for o in owners("/dl/Show/ep.mkv", [parent, child])] == ["child", "parent"]


def test_prefix_boundary_not_fooled_by_sibling():
    a = _st("a", content_path="/dl/Show")
    assert find("/dl/ShowExtra/x.mkv", [a]) is None


def test_dotdot_escape_is_normalized():
    incomplete = _st("inc", content_path="/dl/incomplete")
    # a lexical /dl/complete/../incomplete must resolve under /dl/incomplete, not /dl/complete
    complete_rec = _st("cmp", content_path="/dl/complete")
    hit = find("/dl/complete/../incomplete/file.mkv", [complete_rec, incomplete])
    assert hit is incomplete


def test_remote_to_local_translation_applied_before_match():
    a = _st("a", content_path="/srv/torrents/Show/ep.mkv")
    hit = find("/mnt/torrent-data/Show/ep.mkv", [a], remote_prefix="/srv/torrents", local_prefix="/mnt/torrent-data")
    assert hit is a


def test_no_false_match_without_translation():
    a = _st("a", content_path="/srv/torrents/Show/ep.mkv")
    assert find("/mnt/torrent-data/Show/ep.mkv", [a]) is None


def test_translation_prefix_boundary():
    # /mnt/torrent-data-old must NOT be translated as if under /mnt/torrent-data
    a = _st("a", content_path="/srv/torrents/Show/ep.mkv")
    hit = find(
        "/mnt/torrent-data-old/Show/ep.mkv", [a], remote_prefix="/srv/torrents", local_prefix="/mnt/torrent-data"
    )
    assert hit is None


def test_root_local_prefix_translation_applied():
    # local_prefix='/' must translate every absolute path (root-aware), not silently no-op
    a = _st("a", content_path="/remote/Show/ep.mkv")
    hit = find("/Show/ep.mkv", [a], remote_prefix="/remote", local_prefix="/")
    assert hit is a


def test_root_local_prefix_no_collision_with_untranslated_path():
    # the real target is /remote/Show; a completed torrent literally at /Show must not be matched
    bogus = _st("bogus", content_path="/Show")
    real = _st("real", content_path="/remote/Show/ep.mkv")
    hit = find("/Show/ep.mkv", [bogus, real], remote_prefix="/remote", local_prefix="/")
    assert hit is real


def test_root_remote_prefix_not_fused():
    # remote_prefix='/' must not fuse into '/Show' incorrectly; suffix re-rooted with a separator
    a = _st("a", content_path="/Show/ep.mkv")
    hit = find("/mnt/x/Show/ep.mkv", [a], remote_prefix="/", local_prefix="/mnt/x")
    assert hit is a
