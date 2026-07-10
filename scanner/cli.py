"""CLI entry point for the Google Photos Duplicate Scanner."""

import argparse
import sys
from pathlib import Path

from tqdm import tqdm

from .hasher import compute_hashes
from .matcher import find_duplicates
from .reporter import generate_report
from .scanner import scan_takeout_folder


def main():
    parser = argparse.ArgumentParser(
        prog="scanner",
        description="Scan a Google Takeout export for duplicate photos.",
    )
    parser.add_argument(
        "takeout_path",
        help="Path to the Google Takeout folder",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=10,
        help="Hamming distance threshold for similar photos (default: 10)",
    )
    parser.add_argument(
        "--time-window",
        type=int,
        default=600,
        help="Seconds within which capture times count as close; pairs taken "
             "farther apart must meet --strict-threshold instead of --threshold. "
             "Set to 0 to disable time-aware matching (default: 600)",
    )
    parser.add_argument(
        "--strict-threshold",
        type=int,
        default=None,
        help="Hamming distance threshold for photo pairs taken far apart in time "
             "(default: half of --threshold)",
    )
    parser.add_argument(
        "--output",
        default="./report",
        help="Output directory for report.html and duplicates.json (default: ./report)",
    )
    parser.add_argument(
        "--exact-only",
        action="store_true",
        help="Only find exact duplicates (skip perceptual hashing)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Custom cache directory for hash results",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers for hashing (default: cpu_count - 1)",
    )

    args = parser.parse_args()

    takeout = Path(args.takeout_path)
    if not takeout.is_dir():
        print(f"Error: '{takeout}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    # Step 1: Scan
    print(f"Scanning {takeout}...")
    entries = scan_takeout_folder(str(takeout))
    print(f"Found {len(entries)} media files.")

    if not entries:
        print("No media files found. Nothing to do.")
        sys.exit(0)

    # Step 2: Hash
    print("Computing hashes...")
    filepaths = [e.path for e in entries]
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    with tqdm(total=len(filepaths), desc="Hashing", unit="file") as pbar:
        hash_results = compute_hashes(
            filepaths,
            cache_dir=cache_dir,
            workers=args.workers,
            progress_callback=lambda _: pbar.update(1),
        )

    errors = [h for h in hash_results if h.error]
    if errors:
        print(f"Warning: {len(errors)} files had hashing errors.")

    # Step 3: Find duplicates
    print("Finding duplicates...")
    groups = find_duplicates(
        entries,
        hash_results,
        threshold=args.threshold,
        exact_only=args.exact_only,
        time_window=args.time_window,
        strict_threshold=args.strict_threshold,
    )

    if not groups:
        print("No duplicates found!")
        sys.exit(0)

    # Step 4: Generate report
    print(f"Generating report in {args.output}/...")
    stats = generate_report(groups, len(entries), args.output)

    print()
    print("=== Summary ===")
    print(f"  Total photos scanned:  {stats['total_photos']}")
    print(f"  Duplicate groups:      {stats['duplicate_groups']}")
    print(f"  Photos to delete:      {stats['duplicates_to_delete']}")
    print(f"  Space recoverable:     {stats['space_recoverable_mb']} MB")
    print()
    print(f"  Report:   {args.output}/report.html")
    print(f"  JSON:     {args.output}/duplicates.json")


if __name__ == "__main__":
    main()
