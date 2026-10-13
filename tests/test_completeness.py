"""Tests for the completeness decide() gate (fail-closed for managed paths)."""

from deluge_utilities import GateDecision, decide


def _s(content_path, *, progress=1.0, is_finished=True, save_path="/dl", content_paths=None, incomplete_paths=None):
    if content_paths is None:
        content_paths = [content_path] if content_path else []
    return {
        "id": content_path,
        "name": content_path,
        "save_path": save_path,
        "content_path": content_path,
        "content_paths": content_paths,
        "incomplete_paths": incomplete_paths or [],
        "progress": progress,
        "is_finished": is_finished,
        "state": "x",
    }


DELUGE = {"path_prefix": "/srv/torrents", "client": "deluge"}
QBT = {
    "path_prefix": "/mnt/torrent-data",
    "client": "qbittorrent",
    "remote_prefix": "/srv/torrents",
    "local_prefix": "/mnt/torrent-data",
}


def test_unmanaged_path_is_non_torrent():
    assert decide("/tmp/x/f.mkv", {}, [DELUGE]) == GateDecision.NON_TORRENT


def test_complete_owning_torrent():
    smap = {"deluge": [_s("/srv/torrents/A", progress=1.0, is_finished=True)]}
    assert decide("/srv/torrents/A/ep.mkv", smap, [DELUGE]) == GateDecision.COMPLETE


def test_partial_owning_torrent():
    smap = {"deluge": [_s("/srv/torrents/A", progress=0.5, is_finished=False)]}
    assert decide("/srv/torrents/A/ep.mkv", smap, [DELUGE]) == GateDecision.INCOMPLETE


def test_no_owning_torrent_is_unknown():
    smap = {"deluge": [_s("/srv/torrents/OTHER")]}
    assert decide("/srv/torrents/A/ep.mkv", smap, [DELUGE]) == GateDecision.UNKNOWN


def test_empty_status_list_is_unknown():
    assert decide("/srv/torrents/A/ep.mkv", {"deluge": []}, [DELUGE]) == GateDecision.UNKNOWN


def test_client_absent_is_unknown():
    assert decide("/srv/torrents/A/ep.mkv", {}, [DELUGE]) == GateDecision.UNKNOWN


def test_client_none_is_unknown():
    assert decide("/srv/torrents/A/ep.mkv", {"deluge": None}, [DELUGE]) == GateDecision.UNKNOWN


def test_nested_incomplete_child_forces_incomplete():
    # a completed parent must NOT mask an incomplete child that also owns the path
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s("/srv/torrents/Show/ep.mkv", progress=0.3, is_finished=False),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.INCOMPLETE


def test_remote_to_local_translation_for_qbt():
    smap = {"qbittorrent": [_s("/srv/torrents/Show", progress=1.0, is_finished=True)]}
    assert decide("/mnt/torrent-data/Show/ep.mkv", smap, [QBT]) == GateDecision.COMPLETE


def test_translation_boundary_not_fooled():
    smap = {"qbittorrent": [_s("/srv/torrents/Show", progress=1.0, is_finished=True)]}
    # /mnt/torrent-data-old is not under /mnt/torrent-data -> unmanaged -> NON_TORRENT
    assert decide("/mnt/torrent-data-old/Show/ep.mkv", smap, [QBT]) == GateDecision.NON_TORRENT


def test_longest_prefix_wins():
    broad = {"path_prefix": "/data", "client": "deluge"}
    nested = {"path_prefix": "/data/nested", "client": "qbittorrent"}
    smap = {
        "deluge": [_s("/data/other", progress=0.1, is_finished=False)],
        "qbittorrent": [_s("/data/nested/Show", progress=1.0, is_finished=True)],
    }
    assert decide("/data/nested/Show/ep.mkv", smap, [broad, nested]) == GateDecision.COMPLETE


def test_root_prefix_rule_is_honored():
    root = {"path_prefix": "/", "client": "deluge"}
    smap = {"deluge": [_s("/anywhere/Show", progress=1.0, is_finished=True)]}
    assert decide("/anywhere/Show/ep.mkv", smap, [root]) == GateDecision.COMPLETE


def test_directory_query_with_nested_incomplete_child():
    # query IS a completed torrent's dir but a separate incomplete torrent is nested inside it;
    # deleting the dir would destroy the child -> must NOT report COMPLETE.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s("/srv/torrents/Show/Season2", progress=0.4, is_finished=False),
        ]
    }
    assert decide("/srv/torrents/Show", smap, [DELUGE]) == GateDecision.INCOMPLETE


def test_incomplete_root_owner_not_masked_by_nested_complete():
    smap = {
        "deluge": [
            _s("/", progress=0.2, is_finished=False),
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.INCOMPLETE


def test_double_slash_query_still_managed():
    smap = {"deluge": [_s("/srv/torrents/Show", progress=1.0, is_finished=True)]}
    # a leading '//' must not escape the '/srv/torrents' rule -> not a false NON_TORRENT
    assert decide("//srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.COMPLETE


def test_unmappable_incomplete_torrent_is_not_masked_by_complete_parent():
    # an incomplete torrent with content_path=None (ambiguous multi-root) whose save_path overlaps
    # the query must NOT be hidden by a completed parent -> fail-closed, never a false COMPLETE.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=0.3, is_finished=False, save_path="/srv/torrents/Show"),
        ]
    }
    assert decide("/srv/torrents/Show", smap, [DELUGE]) == GateDecision.UNKNOWN


def test_unmappable_incomplete_under_shared_save_path_blocks_complete():
    # complete owner of the file, but an unmappable incomplete torrent sharing the save dir could
    # live anywhere under it -> cannot certify COMPLETE.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=0.1, is_finished=False, save_path="/srv/torrents"),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.UNKNOWN


def test_unmappable_but_complete_torrent_does_not_block():
    # a COMPLETE torrent without content_path is no deletion threat -> must not force UNKNOWN.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=1.0, is_finished=True, save_path="/srv/torrents/Show"),
        ]
    }
    assert decide("/srv/torrents/Show", smap, [DELUGE]) == GateDecision.COMPLETE


def test_unmappable_incomplete_in_unrelated_tree_is_ignored():
    # an unmappable incomplete torrent whose save_path does not overlap the query is irrelevant.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=0.2, is_finished=False, save_path="/srv/other"),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.COMPLETE


def test_multiroot_incomplete_does_not_block_unrelated_sibling():
    # a multi-root incomplete torrent sharing the save dir is placed PRECISELY by its footprint,
    # so it must NOT force UNKNOWN for an unrelated completed sibling under the same save dir.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(
                None,
                progress=0.3,
                is_finished=False,
                save_path="/srv/torrents",
                content_paths=["/srv/torrents/readme.txt", "/srv/torrents/data"],
            ),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.COMPLETE


def test_multiroot_incomplete_blocks_when_a_footprint_overlaps():
    # when the query overlaps one of the multi-root torrent's actual top-level paths -> INCOMPLETE.
    smap = {
        "deluge": [
            _s(
                None,
                progress=0.3,
                is_finished=False,
                save_path="/srv/torrents",
                content_paths=["/srv/torrents/readme.txt", "/srv/torrents/data"],
            ),
        ]
    }
    assert decide("/srv/torrents/data/x.bin", smap, [DELUGE]) == GateDecision.INCOMPLETE


def test_globally_unplaceable_incomplete_forces_unknown():
    # an incomplete torrent with NO usable footprint AND no usable save_path cannot be placed
    # anywhere -> it must block EVERY managed query, even one with a complete owner.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=0.0, is_finished=False, save_path=None, content_paths=[]),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.UNKNOWN


def test_metadata_fetching_torrent_not_masked_by_complete_sibling():
    # a metadata-fetching torrent (is_finished=False, empty footprint) whose save_path overlaps the
    # query must NOT be treated as done and masked by a completed sibling -> fail-closed.
    smap = {
        "deluge": [
            _s("/srv/torrents/Show", progress=1.0, is_finished=True),
            _s(None, progress=0.0, is_finished=False, save_path="/srv/torrents", content_paths=[]),
        ]
    }
    assert decide("/srv/torrents/Show/ep.mkv", smap, [DELUGE]) == GateDecision.UNKNOWN


def test_rootless_complete_torrent_does_not_certify_unrelated_path():
    # a complete rootless torrent reports an unknown footprint (content_paths=[]); it must NOT be
    # able to certify an arbitrary path under its save dir that it does not actually own.
    qbt_dl = {"path_prefix": "/dl", "client": "qbittorrent"}
    smap = {"qbittorrent": [_s(None, progress=1.0, is_finished=True, save_path="/dl", content_paths=[])]}
    assert decide("/dl/unrelated/partial.mkv", smap, [qbt_dl]) == GateDecision.UNKNOWN


def _partial():
    # a finished-looking torrent (is_finished True) with one fully-downloaded file and one skipped
    # partial file under the same folder footprint.
    return {
        "deluge": [
            _s(
                "/srv/torrents/Show",
                progress=1.0,
                is_finished=True,
                incomplete_paths=["/srv/torrents/Show/e2.mkv"],
            )
        ]
    }


def test_directory_query_over_partial_file_is_incomplete():
    # deleting the folder would destroy the partial file -> must NOT be COMPLETE
    assert decide("/srv/torrents/Show", _partial(), [DELUGE]) == GateDecision.INCOMPLETE


def test_partial_file_itself_is_incomplete():
    assert decide("/srv/torrents/Show/e2.mkv", _partial(), [DELUGE]) == GateDecision.INCOMPLETE


def test_sibling_complete_file_stays_certifiable():
    # a fully-downloaded sibling file does not overlap the partial file -> still COMPLETE
    assert decide("/srv/torrents/Show/e1.mkv", _partial(), [DELUGE]) == GateDecision.COMPLETE
