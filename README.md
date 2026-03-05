# Google Photos Duplicate Finder

Find and remove duplicate photos from your Google Photos library using Google Takeout exports.

## Overview

1. **Python CLI Scanner** — Scans a Google Takeout export, identifies exact and visually similar duplicates, generates an HTML report and `duplicates.json`
2. **Chrome Extension** — Loads `duplicates.json` and bulk-deletes duplicates from the Google Photos web UI

## Python Scanner

### Install

```bash
pip install -r requirements.txt
```

### Usage

```bash
python -m scanner /path/to/Takeout --output ./report
```

**Options:**
- `--threshold N` — Hamming distance for similarity matching (default: 10, lower = stricter)
- `--exact-only` — Only find exact duplicates (faster, skip perceptual hashing)
- `--output DIR` — Output directory (default: `./report`)
- `--cache-dir DIR` — Custom hash cache location
- `--workers N` — Number of parallel hashing workers

### Output

- `report/report.html` — Visual report with duplicate groups, thumbnails, and keep/delete recommendations
- `report/duplicates.json` — Machine-readable duplicate list for the Chrome extension

## Chrome Extension

### Install

1. Open `chrome://extensions/`
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `extension/` folder

### Usage

1. Open [photos.google.com](https://photos.google.com)
2. Click the extension icon
3. Load `duplicates.json` from the scanner output
4. Set delay between deletions (default: 3 seconds)
5. Click **Start Deletion**

The extension searches for each duplicate photo and moves it to trash. You can pause/resume/stop at any time.

### Notes

- Test on a small batch first (2-3 photos)
- Deleted photos go to Google Photos trash (recoverable for 60 days)
- The extension navigates the Google Photos UI, so keep the tab active during deletion
