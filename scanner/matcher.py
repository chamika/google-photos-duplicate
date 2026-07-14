"""Find duplicate groups: exact (SHA256) and visually similar (dhash Hamming distance)."""

import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Optional

import numpy as np
from tqdm import tqdm

from .hasher import HashResult
from .scanner import PhotoEntry

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)

# Google Takeout duplicate-name markers: IMG_001-edited.jpg, IMG_001(1).jpg
_VARIANT_SUFFIX_RE = re.compile(r"(?:-edited|\(\d+\))$")


def _normalized_stem(filename: str) -> str:
    """Strip Takeout duplicate-name markers from a filename's stem."""
    stem = Path(filename).stem
    while True:
        stripped = _VARIANT_SUFFIX_RE.sub("", stem)
        if stripped == stem:
            return stem
        stem = stripped


def _haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters; NaN inputs yield NaN."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * np.arcsin(np.sqrt(a))


@dataclass
class DuplicateCandidate:
    entry: PhotoEntry
    hash_result: HashResult


@dataclass
class DuplicateGroup:
    group_id: int
    match_type: str  # "exact" or "similar"
    keep: DuplicateCandidate
    delete: list[DuplicateCandidate] = field(default_factory=list)
    hamming_distance: Optional[int] = None  # For similar matches


def _pick_best(
    candidates: list[DuplicateCandidate],
    protected: frozenset[str] = frozenset(),
) -> tuple[DuplicateCandidate, list[DuplicateCandidate]]:
    """Choose the best photo to keep from a group of duplicates.

    Priority: protected (excluded-album) photos first, then largest file size →
    highest resolution → earliest date (original).
    """
    def sort_key(c: DuplicateCandidate):
        size = c.entry.size or 0
        resolution = c.entry.resolution
        # Earlier capture time = better (the original); missing timestamps sort last
        date = c.entry.timestamp if c.entry.timestamp is not None else float("inf")
        return (c.entry.path not in protected, -size, -resolution, date)

    sorted_candidates = sorted(candidates, key=sort_key)
    return sorted_candidates[0], sorted_candidates[1:]


def _protected_paths(
    entries: list[PhotoEntry],
    hash_results: list[HashResult],
    exclude_albums: list[str],
) -> frozenset[str]:
    """Paths that must never become delete candidates.

    A photo is protected when its immediate album folder matches an excluded
    album name (case-insensitive). Protection propagates to identical copies
    elsewhere (same file content or same Google Photos URL): Takeout duplicates
    album photos into other folders, but they are one photo in Google Photos,
    so deleting any copy would remove it from the excluded album too.
    """
    excluded = {a.lower() for a in exclude_albums}
    direct = [e for e in entries if Path(e.path).parent.name.lower() in excluded]
    if not direct:
        return frozenset()

    protected = {e.path for e in direct}
    path_to_sha = {h.filepath: h.sha256 for h in hash_results if h.sha256}
    shas = {path_to_sha[p] for p in protected if p in path_to_sha}
    urls = {e.url for e in direct if e.url}
    for e in entries:
        if path_to_sha.get(e.path) in shas or (e.url and e.url in urls):
            protected.add(e.path)
    return frozenset(protected)


def find_duplicates(
    entries: list[PhotoEntry],
    hash_results: list[HashResult],
    threshold: int = 10,
    exact_only: bool = False,
    time_window: int = 600,
    strict_threshold: Optional[int] = None,
    geo_window: float = 1000.0,
    exclude_albums: Optional[list[str]] = None,
) -> list[DuplicateGroup]:
    """Find duplicate photo groups.

    Args:
        entries: List of PhotoEntry objects from scanning.
        hash_results: Corresponding HashResult objects.
        threshold: Maximum Hamming distance for similar photos (default 10).
        exact_only: If True, skip perceptual hashing.
        time_window: Seconds within which two capture times count as "close".
            Pairs taken close together (bursts, edits, re-uploads) match at the
            full threshold; pairs far apart must meet strict_threshold instead,
            filtering out look-alike but unrelated photos. Set <= 0 to disable.
        strict_threshold: Maximum Hamming distance for pairs whose capture
            times or locations disagree (default: threshold // 2). Pairs with
            unknown capture times/locations keep the full threshold.
        geo_window: Meters within which two GPS locations count as "close".
            Pairs tagged farther apart than this must meet strict_threshold,
            like far-apart capture times. Set <= 0 to disable.
        exclude_albums: Album folder names whose photos are never marked for
            deletion. Protected photos are preferred as the group's "keep";
            identical copies elsewhere are protected too. Groups with nothing
            left to delete are dropped.

    Returns:
        List of DuplicateGroup objects.
    """
    if strict_threshold is None:
        strict_threshold = threshold // 2

    protected = _protected_paths(entries, hash_results, exclude_albums) if exclude_albums else frozenset()
    # Build lookup maps
    path_to_entry: dict[str, PhotoEntry] = {e.path: e for e in entries}
    path_to_hash: dict[str, HashResult] = {h.filepath: h for h in hash_results}

    groups: list[DuplicateGroup] = []
    group_id = 0

    # Phase 1: Exact duplicates (group by SHA256)
    sha_groups: dict[str, list[str]] = {}
    for hr in hash_results:
        if hr.error or not hr.sha256:
            continue
        sha_groups.setdefault(hr.sha256, []).append(hr.filepath)

    exact_duplicate_paths: set[str] = set()
    for sha, paths in sha_groups.items():
        if len(paths) < 2:
            continue

        candidates = []
        for p in paths:
            if p in path_to_entry and p in path_to_hash:
                candidates.append(DuplicateCandidate(
                    entry=path_to_entry[p],
                    hash_result=path_to_hash[p],
                ))

        if len(candidates) < 2:
            continue

        keep, delete = _pick_best(candidates, protected)
        delete = [c for c in delete if c.entry.path not in protected]
        if not delete:
            # Everything in the group is protected; leave members for phase 2
            continue

        group_id += 1
        groups.append(DuplicateGroup(
            group_id=group_id,
            match_type="exact",
            keep=keep,
            delete=delete,
        ))
        exact_duplicate_paths.update(p for p in paths)

    if exact_only:
        return groups

    # Phase 2: Similar photos (dhash Hamming distance)
    # Collect photos that weren't part of exact duplicate groups (keep representatives)
    kept_paths = {g.keep.hash_result.filepath for g in groups}
    remaining: list[tuple[str, str]] = []  # (filepath, dhash)
    for hr in hash_results:
        if hr.error or not hr.dhash:
            continue
        # Include if: not in any exact group, or is the "keep" representative
        if hr.filepath not in exact_duplicate_paths or hr.filepath in kept_paths:
            remaining.append((hr.filepath, hr.dhash))

    # Vectorized pairwise comparison with union-find for clustering.
    # Pre-decode each dhash hex string into a uint8 byte row once, so the inner
    # comparison is a vectorized XOR + popcount instead of ~n^2 hex parses.
    n = len(remaining)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Track minimum distances within clusters
    min_distances: dict[tuple[int, int], int] = {}

    if n > 1:
        # Stack all dhashes into an (n, hash_bytes) uint8 array.
        hash_bytes = len(remaining[0][1]) // 2
        H = np.empty((n, hash_bytes), dtype=np.uint8)
        for k in range(n):
            H[k] = np.frombuffer(bytes.fromhex(remaining[k][1]), dtype=np.uint8)

        # Capture times (epoch seconds) and GPS coordinates aligned with
        # `remaining`, NaN when unknown.
        T = np.full(n, np.nan)
        LAT = np.full(n, np.nan)
        LON = np.full(n, np.nan)
        for k in range(n):
            entry = path_to_entry.get(remaining[k][0])
            if entry is None:
                continue
            if entry.timestamp is not None:
                T[k] = entry.timestamp
            if entry.geo:
                LAT[k] = entry.geo["latitude"]
                LON[k] = entry.geo["longitude"]

        for i in tqdm(range(n - 1), desc="Matching", unit="photo"):
            xor = np.bitwise_xor(H[i + 1:], H[i])
            dists = _POPCOUNT[xor].sum(axis=1)
            # Pairs whose metadata disagrees (capture times or GPS locations far
            # apart) must meet the stricter threshold; NaN comparisons are False,
            # so unknown metadata keeps the full threshold.
            demote = None
            if time_window > 0:
                demote = np.abs(T[i + 1:] - T[i]) > time_window
            if geo_window > 0:
                far_in_space = _haversine_meters(LAT[i], LON[i], LAT[i + 1:], LON[i + 1:]) > geo_window
                demote = far_in_space if demote is None else demote | far_in_space
            allowed = threshold if demote is None else np.where(demote, strict_threshold, threshold)
            matches = np.flatnonzero(dists <= allowed)
            for off in matches:
                j = i + 1 + int(off)
                union(i, j)
                min_distances[(i, j)] = int(dists[off])

        # Phase 2b: Takeout name variants. A file whose name only differs by a
        # duplicate marker (IMG_001-edited.jpg, IMG_001(1).jpg) sitting in the
        # same directory as its base is near-certainly derived from it, so allow
        # a relaxed distance for those pairs (edits can shift the hash a lot).
        relaxed_threshold = threshold * 2
        is_variant = [Path(fp).stem != _normalized_stem(fp) for fp, _ in remaining]
        by_name: dict[tuple[str, str, str], list[int]] = {}
        for k, (fp, _) in enumerate(remaining):
            p = Path(fp)
            by_name.setdefault((str(p.parent), _normalized_stem(fp), p.suffix.lower()), []).append(k)
        for indices in by_name.values():
            if len(indices) < 2:
                continue
            for a, b in combinations(indices, 2):
                if not (is_variant[a] or is_variant[b]):
                    continue
                dist = int(_POPCOUNT[np.bitwise_xor(H[a], H[b])].sum())
                if dist <= relaxed_threshold:
                    union(a, b)
                    min_distances.setdefault((min(a, b), max(a, b)), dist)

    # Collect clusters
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    for indices in clusters.values():
        if len(indices) < 2:
            continue

        candidates = []
        for idx in indices:
            fp = remaining[idx][0]
            if fp in path_to_entry and fp in path_to_hash:
                candidates.append(DuplicateCandidate(
                    entry=path_to_entry[fp],
                    hash_result=path_to_hash[fp],
                ))

        if len(candidates) < 2:
            continue

        # Find minimum hamming distance in this cluster
        cluster_dist = None
        for i_idx in range(len(indices)):
            for j_idx in range(i_idx + 1, len(indices)):
                pair = (min(indices[i_idx], indices[j_idx]), max(indices[i_idx], indices[j_idx]))
                if pair in min_distances:
                    d = min_distances[pair]
                    if cluster_dist is None or d < cluster_dist:
                        cluster_dist = d

        keep, delete = _pick_best(candidates, protected)
        delete = [c for c in delete if c.entry.path not in protected]
        if not delete:
            continue

        group_id += 1
        groups.append(DuplicateGroup(
            group_id=group_id,
            match_type="similar",
            keep=keep,
            delete=delete,
            hamming_distance=cluster_dist,
        ))

    return groups
