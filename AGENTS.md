# AGENTS.md

## Project Overview

Google Photos Duplicate Finder & Deleter — a two-part tool that identifies duplicate photos in Google Takeout exports and bulk-deletes them from Google Photos.

### Components

1. **Python CLI Scanner** (`scanner/`) — Scans Google Takeout exports, finds exact (SHA256) and visually similar (dhash) duplicates, generates an interactive HTML report and `duplicates.json`.
2. **Chrome Extension** (`extension/`) — Loads `duplicates.json`, navigates Google Photos by direct URL, and deletes each photo via the web UI.

## Architecture

### Scanner (`scanner/`)

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point for `python -m scanner` |
| `cli.py` | Argument parsing, orchestrates scan → hash → match → report pipeline |
| `scanner.py` | Walks Takeout folder, indexes media files, parses `.json` sidecar metadata |
| `hasher.py` | SHA256 + dhash (perceptual) hashing with file-based caching and multiprocessing |
| `matcher.py` | Groups duplicates: exact by SHA256, similar by dhash Hamming distance with union-find clustering |
| `reporter.py` | Generates `report.html` (Jinja2) and `duplicates.json` |
| `templates/report.html` | Interactive HTML report with checkboxes, live stats, and JSON export |

**Data flow:** `scan_takeout_folder()` → `compute_hashes()` → `find_duplicates()` → `generate_report()`

**Key data types:**
- `PhotoEntry` — a scanned media file with path, dimensions, date, optional Google Photos URL from sidecar metadata
- `HashResult` — SHA256 + dhash for a file
- `DuplicateCandidate` — a `PhotoEntry` + `HashResult` pair
- `DuplicateGroup` — one "keep" candidate + list of "delete" candidates, with match type and hamming distance

**Keep selection priority:** largest file size → highest resolution → earliest date.

### Chrome Extension (`extension/`)

| File | Purpose |
|------|---------|
| `manifest.json` | Manifest V3, permissions for `photos.google.com` |
| `popup.html` / `popup.js` / `styles.css` | UI for loading JSON, configuring delay, start/pause/stop controls |
| `background.js` | Service worker: manages deletion queue, navigates tabs to photo URLs, sends delete commands |
| `content.js` | Content script: deletes the currently-viewed photo by clicking trash button or `#` keyboard shortcut |

**Deletion flow:** `popup.js` builds queue from `duplicates.json` → `background.js` navigates tab to each photo's URL → waits for load → sends `delete-current-photo` message to `content.js` → content script clicks delete and confirms.

**Photo identification:** The extension navigates directly to the photo's Google Photos URL (from Takeout sidecar `url` field). This requires the `url` field to be present in the sidecar metadata.

## `duplicates.json` Schema

```json
{
  "generated": "ISO8601",
  "groups": [
    {
      "id": 1,
      "match_type": "exact|similar",
      "hamming_distance": null,
      "keep": { "filename", "path", "date", "size", "size_formatted", "width", "height", "resolution", "url?" },
      "delete": [ ...same shape as keep... ]
    }
  ],
  "stats": { "total_photos", "duplicate_groups", "duplicates_to_delete", "space_recoverable_mb" }
}
```

The HTML report's **Export duplicates.json** button generates this same schema from the user's interactive selections.

## Development

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Dependencies:** Pillow, imagehash, tqdm, Jinja2

### Running the scanner

```bash
python -m scanner /path/to/Takeout --output ./report
```

Key flags: `--threshold N` (hamming distance, default 10), `--exact-only`, `--workers N`, `--cache-dir DIR`.

### Loading the extension

1. `chrome://extensions/` → Developer mode → Load unpacked → select `extension/`
2. Open `photos.google.com`, click extension, load `duplicates.json`, start deletion

### Conventions

- Python 3.9+ (uses `list[...]` type hints, `Optional` from typing)
- No test framework currently in use
- HTML template uses Jinja2 with `autoescape=True`
- Extension uses vanilla JS (no build step, no framework)
- Hash cache stored at `~/.cache/gphotos-dedup/hashes.json`

### Important notes

- The `report.html` template uses `{{ groups | tojson }}` to embed group data for client-side JavaScript — the `photos` list in the template uses a flat structure with `auto_delete` booleans, different from `duplicates.json`'s `keep`/`delete` split
- Jinja2 version may not support `loop.parent` — use `{% set %}` before inner loops to capture outer loop variables
- The `url` field on `PhotoEntry` comes from the Google Takeout sidecar `.json` files and is critical for the extension's direct-navigation deletion approach
- Sidecar files follow several naming patterns (see `scanner.py:_find_sidecar`)
