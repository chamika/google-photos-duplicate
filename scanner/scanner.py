"""Walk a Google Takeout folder, index all images and parse sidecar metadata."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from .hasher import SUPPORTED_EXTENSIONS

SIDECAR_KEYS_MAP = {
    "photoTakenTime": "date_taken",
    "creationTime": "creation_time",
    "description": "description",
    "geoData": "geo",
}


@dataclass
class PhotoEntry:
    path: str
    filename: str
    size: int  # bytes
    width: Optional[int] = None
    height: Optional[int] = None
    date_taken: Optional[str] = None
    description: Optional[str] = None
    geo: Optional[dict] = None
    url: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def resolution(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return 0


def _parse_sidecar(json_path: Path) -> dict:
    """Parse a Google Takeout companion .json sidecar file."""
    try:
        with open(json_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    result = {}
    if "photoTakenTime" in data:
        result["date_taken"] = data["photoTakenTime"].get("formatted")
    if "creationTime" in data:
        result["creation_time"] = data["creationTime"].get("formatted")
    if "description" in data:
        result["description"] = data["description"]
    if "geoData" in data:
        geo = data["geoData"]
        if geo.get("latitude", 0) != 0 or geo.get("longitude", 0) != 0:
            result["geo"] = {
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
            }
    if "url" in data and data["url"]:
        result["url"] = data["url"]
    return result


def _get_image_dimensions(filepath: str) -> tuple[Optional[int], Optional[int]]:
    """Get image width and height. Returns (None, None) for videos or on error."""
    ext = Path(filepath).suffix.lower()
    if ext in {".mp4", ".mov"}:
        return None, None
    try:
        with Image.open(filepath) as img:
            return img.size  # (width, height)
    except Exception:
        return None, None


def _find_sidecar(filepath: Path) -> Optional[Path]:
    """Find the companion .json sidecar for a media file.

    Google Takeout uses several naming patterns:
    - IMG_001.jpg.json
    - IMG_001.json (same stem)
    - IMG_001.jpg.supplemental-metadata.json
    """
    # Pattern 1: filename.ext.json
    sidecar = filepath.parent / (filepath.name + ".json")
    if sidecar.exists():
        return sidecar

    # Pattern 2: filename.json (without media extension)
    sidecar = filepath.parent / (filepath.stem + ".json")
    if sidecar.exists():
        return sidecar

    # Pattern 3: filename.ext.supplemental-metadata.json (newer Takeout format)
    sidecar = filepath.parent / (filepath.name + ".supplemental-metadata.json")
    if sidecar.exists():
        return sidecar

    return None


def scan_takeout_folder(
    takeout_path: str,
    progress_callback=None,
) -> list[PhotoEntry]:
    """Recursively walk a Google Takeout folder and index all supported media files.

    Args:
        takeout_path: Path to the Takeout folder.
        progress_callback: Called with each PhotoEntry as it's discovered.

    Returns:
        List of PhotoEntry objects.
    """
    root = Path(takeout_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Takeout folder not found: {takeout_path}")

    entries: list[PhotoEntry] = []

    for dirpath, _, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                continue

            stat = fpath.stat()
            width, height = _get_image_dimensions(str(fpath))

            # Parse sidecar metadata
            sidecar_path = _find_sidecar(fpath)
            meta = _parse_sidecar(sidecar_path) if sidecar_path else {}

            entry = PhotoEntry(
                path=str(fpath),
                filename=fname,
                size=stat.st_size,
                width=width,
                height=height,
                date_taken=meta.get("date_taken") or meta.get("creation_time"),
                description=meta.get("description"),
                geo=meta.get("geo"),
                url=meta.get("url"),
                metadata=meta,
            )
            entries.append(entry)
            if progress_callback:
                progress_callback(entry)

    return entries
