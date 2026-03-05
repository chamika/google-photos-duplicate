"""Find duplicate groups: exact (SHA256) and visually similar (dhash Hamming distance)."""

from dataclasses import dataclass, field
from typing import Optional

import imagehash

from .hasher import HashResult
from .scanner import PhotoEntry


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
        # Earlier date = better, so we negate the string comparison (or use empty for missing)
        date = c.entry.date_taken or "9999"
        return (-size, -resolution, date)

    sorted_candidates = sorted(candidates, key=sort_key)
    return sorted_candidates[0], sorted_candidates[1:]


def _hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hex-encoded imagehash strings."""
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    return h1 - h2


def find_duplicates(
    entries: list[PhotoEntry],
    hash_results: list[HashResult],
    threshold: int = 10,
    exact_only: bool = False,
) -> list[DuplicateGroup]:
    """Find duplicate photo groups.

    Args:
        entries: List of PhotoEntry objects from scanning.
        hash_results: Corresponding HashResult objects.
        threshold: Maximum Hamming distance for similar photos (default 10).
        exact_only: If True, skip perceptual hashing.

    Returns:
        List of DuplicateGroup objects.
    """
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

    # Brute-force pairwise comparison with union-find for clustering
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

    for i in range(n):
        for j in range(i + 1, n):
            dist = _hamming_distance(remaining[i][1], remaining[j][1])
            if dist <= threshold:
                union(i, j)
                pair = (min(i, j), max(i, j))
                min_distances[pair] = dist

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
