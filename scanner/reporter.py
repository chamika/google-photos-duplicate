"""Generate HTML report and duplicates.json from duplicate groups."""

import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .matcher import DuplicateGroup
from .scanner import PhotoEntry


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _candidate_to_dict(candidate) -> dict:
    entry = candidate.entry
    return {
        "filename": entry.filename,
        "path": entry.path,
        "date": entry.date_taken or "Unknown",
        "size": entry.size,
        "size_formatted": _format_size(entry.size),
        "width": entry.width,
        "height": entry.height,
        "resolution": f"{entry.width}x{entry.height}" if entry.width and entry.height else "Unknown",
    }


def generate_duplicates_json(
    groups: list[DuplicateGroup],
    total_photos: int,
    output_path: Path,
):
    """Write duplicates.json for the Chrome extension."""
    delete_count = sum(len(g.delete) for g in groups)
    recoverable_bytes = sum(c.entry.size for g in groups for c in g.delete)

    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "groups": [
            {
                "id": g.group_id,
                "match_type": g.match_type,
                "hamming_distance": g.hamming_distance,
                "keep": _candidate_to_dict(g.keep),
                "delete": [_candidate_to_dict(c) for c in g.delete],
            }
            for g in groups
        ],
        "stats": {
            "total_photos": total_photos,
            "duplicate_groups": len(groups),
            "duplicates_to_delete": delete_count,
            "space_recoverable_mb": round(recoverable_bytes / (1024 * 1024), 1),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return data["stats"]


def generate_html_report(
    groups: list[DuplicateGroup],
    total_photos: int,
    output_path: Path,
):
    """Render the HTML report using the Jinja2 template."""
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("report.html")

    delete_count = sum(len(g.delete) for g in groups)
    recoverable_bytes = sum(c.entry.size for g in groups for c in g.delete)

    template_groups = []
    for g in groups:
        keep_dict = _candidate_to_dict(g.keep)
        keep_dict["auto_delete"] = False
        photos = [keep_dict]
        for c in g.delete:
            d = _candidate_to_dict(c)
            d["auto_delete"] = True
            photos.append(d)
        template_groups.append({
            "id": g.group_id,
            "match_type": g.match_type,
            "hamming_distance": g.hamming_distance,
            "photos": photos,
        })

    html = template.render(
        groups=template_groups,
        stats={
            "total_photos": total_photos,
            "duplicate_groups": len(groups),
            "duplicates_to_delete": delete_count,
            "space_recoverable_mb": round(recoverable_bytes / (1024 * 1024), 1),
        },
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)


def generate_report(
    groups: list[DuplicateGroup],
    total_photos: int,
    output_dir: str,
) -> dict:
    """Generate both HTML report and duplicates.json.

    Returns:
        Stats dictionary.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    stats = generate_duplicates_json(groups, total_photos, out / "duplicates.json")
    generate_html_report(groups, total_photos, out / "report.html")

    return stats
