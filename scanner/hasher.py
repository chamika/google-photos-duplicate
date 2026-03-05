"""File hashing (SHA256) and perceptual hashing (dhash) with caching and parallel computation."""

import hashlib
import json
import os
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Optional

import imagehash
from PIL import Image

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gphotos-dedup"
HASH_SIZE = 16  # 256-bit dhash

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass
class HashResult:
    filepath: str
    sha256: str
    dhash: Optional[str]  # None for videos or files that can't be perceptually hashed
    error: Optional[str] = None


def _compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_dhash(filepath: str) -> Optional[str]:
    ext = Path(filepath).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return None
    try:
        img = Image.open(filepath)
        return str(imagehash.dhash(img, hash_size=HASH_SIZE))
    except Exception:
        return None


def _hash_single_file(filepath: str) -> HashResult:
    """Compute both SHA256 and dhash for a single file."""
    try:
        sha256 = _compute_sha256(filepath)
        dhash = _compute_dhash(filepath)
        return HashResult(filepath=filepath, sha256=sha256, dhash=dhash)
    except Exception as e:
        return HashResult(filepath=filepath, sha256="", dhash=None, error=str(e))


class HashCache:
    """Persistent hash cache keyed by filepath + mtime to avoid recomputation."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_file = self.cache_dir / "hashes.json"
        self.cache: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.cache = {}

    def save(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self.cache, f)

    def _cache_key(self, filepath: str) -> str:
        mtime = os.path.getmtime(filepath)
        return f"{filepath}::{mtime}"

    def get(self, filepath: str) -> Optional[HashResult]:
        key = self._cache_key(filepath)
        if key in self.cache:
            entry = self.cache[key]
            return HashResult(
                filepath=filepath,
                sha256=entry["sha256"],
                dhash=entry.get("dhash"),
            )
        return None

    def put(self, result: HashResult):
        if result.error:
            return
        key = self._cache_key(result.filepath)
        self.cache[key] = {
            "sha256": result.sha256,
            "dhash": result.dhash,
        }


def compute_hashes(
    filepaths: list[str],
    cache_dir: Optional[Path] = None,
    workers: Optional[int] = None,
    progress_callback=None,
) -> list[HashResult]:
    """Compute hashes for a list of files using multiprocessing and caching.

    Args:
        filepaths: List of file paths to hash.
        cache_dir: Custom cache directory.
        workers: Number of parallel workers (default: cpu_count).
        progress_callback: Called with each HashResult as it completes.

    Returns:
        List of HashResult objects.
    """
    cache = HashCache(cache_dir)
    results: list[HashResult] = []
    to_compute: list[str] = []

    # Check cache first
    for fp in filepaths:
        cached = cache.get(fp)
        if cached:
            results.append(cached)
            if progress_callback:
                progress_callback(cached)
        else:
            to_compute.append(fp)

    if to_compute:
        num_workers = workers or max(1, cpu_count() - 1)
        # Use multiprocessing for large batches, sequential for small ones
        if len(to_compute) > 50:
            with Pool(num_workers) as pool:
                for result in pool.imap_unordered(_hash_single_file, to_compute):
                    cache.put(result)
                    results.append(result)
                    if progress_callback:
                        progress_callback(result)
        else:
            for fp in to_compute:
                result = _hash_single_file(fp)
                cache.put(result)
                results.append(result)
                if progress_callback:
                    progress_callback(result)

        cache.save()

    return results
