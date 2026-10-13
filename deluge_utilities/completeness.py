"""Torrent-folder completeness decision, fail-closed for managed paths.

``decide()`` maps a filesystem path to one of four outcomes using a per-client
batched status map (from :meth:`BaseTorrentClient.all_torrents_status`) and a list of
path rules. A path under a managed ``path_prefix`` whose owning torrent cannot be
confirmed complete resolves to ``UNKNOWN`` (the caller should skip/retry) — it is never
optimistically treated as complete. Only a path under NO managed prefix is
``NON_TORRENT``.
"""

from enum import Enum

from .base_client import BaseTorrentClient


class GateDecision(str, Enum):
    """Outcome of a completeness check for a path."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"
    NON_TORRENT = "NON_TORRENT"


def _matching_rule(path: str, rules: list[dict]) -> dict | None:
    """Return the rule with the longest ``path_prefix`` that owns ``path`` (boundary-safe).

    Prefixes are normalized (``/a/`` -> ``/a``); a root ``/`` prefix matches any absolute
    path at lowest priority instead of being silently dropped. First rule wins on an exact
    length tie (deterministic; equal prefixes for different clients are a misconfiguration).
    """
    query = BaseTorrentClient._canon(path)
    best = None
    best_len = -1
    for rule in rules:
        raw = str(rule.get("path_prefix") or "")
        if not raw:
            continue
        prefix = BaseTorrentClient._canon(raw)
        owns = BaseTorrentClient._contains(prefix, query)
        plen = 0 if prefix == "/" else len(prefix)
        if owns and plen > best_len:
            best, best_len = rule, plen
    return best


def decide(path: str, status_map: dict, rules: list[dict]) -> GateDecision:
    """
    Decide the completeness gate for ``path``.

    :param path: Local filesystem path to a file or directory.
    :param status_map: ``{client_key -> list[status] | None}``. ``None`` (or a missing key)
                       means the client was absent/errored for this query.
    :param rules: List of ``{path_prefix, client, remote_prefix?, local_prefix?}`` rules;
                  ``client`` indexes ``status_map``.
    :return: ``COMPLETE`` only when EVERY overlapping torrent is complete AND no unmappable
             incomplete torrent could sit under the path; ``INCOMPLETE`` when any overlapping
             torrent is partial; ``UNKNOWN`` (fail-closed) for a managed path with an absent
             client, no overlapping torrent, or an incomplete torrent whose footprint cannot be
             confirmed; ``NON_TORRENT`` when no rule owns the path.
    """
    rule = _matching_rule(path, rules)
    if rule is None:
        return GateDecision.NON_TORRENT

    statuses = status_map.get(rule.get("client"))
    if statuses is None:
        return GateDecision.UNKNOWN  # client absent/errored -> fail-closed

    remote_prefix = rule.get("remote_prefix")
    local_prefix = rule.get("local_prefix")

    # Overlap in BOTH directions: the torrent that backs the path AND any torrent nested inside a
    # directory query. COMPLETE requires EVERY overlapping torrent complete, so a completed parent
    # never masks an incomplete child (and an incomplete parent never hides behind a complete child).
    overlapping = BaseTorrentClient.find_overlapping_for_path(
        path, statuses, remote_prefix=remote_prefix, local_prefix=local_prefix
    )
    # Backstop: an incomplete torrent whose exact footprint is unknown (content_path=None, e.g. an
    # ambiguous multi-root Deluge torrent) is invisible to the content_path-only overlap above. If
    # its save_path overlaps the query it MIGHT live under the path, so we cannot certify COMPLETE.
    unmappable = BaseTorrentClient.find_unmappable_incomplete(
        path, statuses, remote_prefix=remote_prefix, local_prefix=local_prefix
    )
    # Precise per-file backstop: an individual partial file (e.g. a deselected/skipped file inside a
    # torrent that otherwise reports is_finished) overlapping the query means the subtree still holds
    # in-progress data -> INCOMPLETE, even though the owning torrent looks complete.
    incomplete_files = BaseTorrentClient.find_incomplete_overlaps(
        path, statuses, remote_prefix=remote_prefix, local_prefix=local_prefix
    )

    # A partial file under the query, or a precisely-located incomplete owner, is a definite INCOMPLETE.
    if incomplete_files:
        return GateDecision.INCOMPLETE
    if overlapping and not all(BaseTorrentClient.is_torrent_complete(o) for o in overlapping):
        return GateDecision.INCOMPLETE

    # An incomplete torrent we can't place precisely, but whose save_path overlaps -> can't confirm
    # complete -> fail-closed.
    if unmappable:
        return GateDecision.UNKNOWN

    # Managed path with no torrent overlapping it at all -> fail-closed.
    if not overlapping:
        return GateDecision.UNKNOWN

    return GateDecision.COMPLETE
