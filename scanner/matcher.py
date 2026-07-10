"""Find duplicate groups: exact (SHA256) and visually similar (dhash Hamming distance)."""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from tqdm import tqdm

from .hasher import HashResult
from .scanner import PhotoEntry

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)


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


def _pick_best(candidates: list[DuplicateCandidate]) -> tuple[DuplicateCandidate, list[DuplicateCandidate]]:
    """Choose the best photo to keep from a group of duplicates.

    Priority: largest file size → highest resolution → earliest date (original).
    """
    def sort_key(c: DuplicateCandidate):
        size = c.entry.size or 0
        resolution = c.entry.resolution
        # Earlier capture time = better (the original); missing timestamps sort last
        date = c.entry.timestamp if c.entry.timestamp is not None else float("inf")
        return (-size, -resolution, date)

    sorted_candidates = sorted(candidates, key=sort_key)
    return sorted_candidates[0], sorted_candidates[1:]


def find_duplicates(
    entries: list[PhotoEntry],
    hash_results: list[HashResult],
    threshold: int = 10,
    exact_only: bool = False,
    time_window: int = 600,
    strict_threshold: Optional[int] = None,
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
            times are farther apart than time_window (default: threshold // 2).
            Pairs with unknown capture times keep the full threshold.

    Returns:
        List of DuplicateGroup objects.
    """
    if strict_threshold is None:
        strict_threshold = threshold // 2
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

        group_id += 1
        keep, delete = _pick_best(candidates)
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

        # Capture times (epoch seconds, NaN when unknown) aligned with `remaining`.
        T = np.full(n, np.nan)
        for k in range(n):
            entry = path_to_entry.get(remaining[k][0])
            if entry is not None and entry.timestamp is not None:
                T[k] = entry.timestamp

        for i in tqdm(range(n - 1), desc="Matching", unit="photo"):
            xor = np.bitwise_xor(H[i + 1:], H[i])
            dists = _POPCOUNT[xor].sum(axis=1)
            if time_window > 0:
                # Pairs far apart in time must meet the stricter threshold;
                # NaN comparisons are False, so unknown times keep the full threshold.
                far_in_time = np.abs(T[i + 1:] - T[i]) > time_window
                allowed = np.where(far_in_time, strict_threshold, threshold)
            else:
                allowed = threshold
            matches = np.flatnonzero(dists <= allowed)
            for off in matches:
                j = i + 1 + int(off)
                union(i, j)
                min_distances[(i, j)] = int(dists[off])

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

        group_id += 1
        keep, delete = _pick_best(candidates)
        groups.append(DuplicateGroup(
            group_id=group_id,
            match_type="similar",
            keep=keep,
            delete=delete,
            hamming_distance=cluster_dist,
        ))

    return groups
