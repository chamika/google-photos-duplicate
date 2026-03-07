#!/bin/bash
# Run scanner on each base folder (1st of each group of 3)

for i in $(seq 1 3 48); do
  base=$(printf "%03d" $i)

  if [ -d "/Users/chamika/Downloads/Takeout/Takeout-$base" ]; then
    echo "=== Scanning Takeout-$base ==="
    python -m scanner "/Users/chamika/Downloads/Takeout/Takeout-$base" --output "./report-$base" --threshold 55 2>&1 | tee "./report-$base/console.log"
  else
    echo "Skipping Takeout-$base (not found)"
  fi
done
