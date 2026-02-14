#!/usr/bin/env python3
"""
Notion Export Cleaner
=====================
Takes a Notion "Markdown & CSV" export zip and produces a clean folder
structure with human-readable filenames (Notion IDs stripped).

Handles:
  - Nested zips (Notion wraps large exports in zip-of-zips with Part-N files)
  - 32-char hex IDs appended to file and folder names
  - Intermediate folders that are *only* a hex ID (collapsed out of the path)
  - Duplicate _all.csv files (optionally removed)
  - YAML frontmatter added to database entry markdown files
  - Internal markdown links updated to match cleaned names
  - Top-level Export-UUID wrapper folder flattened
  - index.html removed

Usage:
    python notion_export_cleaner.py <export.zip> [--output <folder>] [--keep-all-csv] [--no-frontmatter]

Example:
    python notion_export_cleaner.py ~/Downloads/Export-2026-02-14.zip --output ~/notion-markdown
"""

import argparse
import csv
import io
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path


# Matches a 32-char hex Notion ID appended after a space in a filename.
# Examples:
#   "My Page 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d.md"  → "My Page.md"
#   "Home e82f1f46f47e4859aef48d9da4875832.md"        → "Home.md"
NOTION_ID_IN_NAME = re.compile(
    r"\s+[0-9a-f]{32}$",
    re.IGNORECASE,
)

# Matches a folder name that is *entirely* a 32-char hex ID (no readable text).
# These are Notion's internal container folders and should be collapsed.
PURE_HEX_FOLDER = re.compile(
    r"^[0-9a-f]{32}$",
    re.IGNORECASE,
)

# Matches the top-level Export-UUID folder Notion creates.
EXPORT_WRAPPER = re.compile(
    r"^Export-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def strip_notion_id(name: str) -> str:
    """Remove the trailing 32-char hex Notion ID from a name."""
    # Split extension off first
    dot_pos = name.rfind(".")
    if dot_pos > 0:
        stem = name[:dot_pos]
        ext = name[dot_pos:]
    else:
        stem = name
        ext = ""

    cleaned = NOTION_ID_IN_NAME.sub("", stem).strip()

    # Also handle _all.csv suffix pattern: "Name ID_all.csv"
    # The ID is already stripped above, so the _all suffix stays for now.
    return f"{cleaned}{ext}" if cleaned else name


def clean_filename(name: str) -> str:
    """Strip Notion ID and normalize the filename."""
    cleaned = strip_notion_id(name)
    cleaned = cleaned.replace("%20", " ")
    return cleaned.strip()


def is_pure_id_folder(name: str) -> bool:
    """Check if a folder name is just a hex ID with no readable text."""
    return bool(PURE_HEX_FOLDER.match(name))


def resolve_conflicts(target: Path) -> Path:
    """If target already exists, append a number to avoid overwriting."""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def extract_nested_zips(zip_path: Path, dest: Path) -> None:
    """
    Extract a Notion export, handling the zip-of-zips pattern.
    Notion large exports contain Part-N.zip files inside the outer zip.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()

        # Check if this is a zip-of-zips (contains only .zip files)
        inner_zips = [m for m in members if m.endswith(".zip")]
        non_zips = [m for m in members if not m.endswith(".zip") and not m.endswith("/")]

        if inner_zips and not non_zips:
            # Zip-of-zips: extract each inner zip
            print(f"  Found {len(inner_zips)} inner zip(s), extracting...")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                zf.extractall(tmp_path)
                for inner_name in sorted(inner_zips):
                    inner_path = tmp_path / inner_name
                    print(f"  Extracting {inner_name}...")
                    with zipfile.ZipFile(inner_path, "r") as inner_zf:
                        inner_zf.extractall(dest)
        else:
            # Normal zip: extract directly
            zf.extractall(dest)


def collapse_id_folders(root: Path) -> int:
    """
    Remove intermediate folders that are pure hex IDs by moving their
    children up one level. Process deepest first.
    """
    collapsed = 0

    # Keep collapsing until no more pure-ID folders remain
    changed = True
    while changed:
        changed = False
        all_dirs = sorted(
            [p for p in root.rglob("*") if p.is_dir() and is_pure_id_folder(p.name)],
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for dir_path in all_dirs:
            if not dir_path.exists():
                continue
            parent = dir_path.parent
            for child in dir_path.iterdir():
                target = resolve_conflicts(parent / child.name)
                child.rename(target)
            dir_path.rmdir()
            collapsed += 1
            changed = True

    return collapsed


def clean_names(root: Path) -> tuple[int, int]:
    """Strip Notion IDs from all file and folder names."""
    files_cleaned = 0
    folders_cleaned = 0

    # Process deepest first so renames don't break parent paths
    all_paths = sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True)

    for path in all_paths:
        if not path.exists():
            continue

        original_name = path.name
        cleaned_name = clean_filename(original_name)

        if cleaned_name != original_name:
            new_path = resolve_conflicts(path.parent / cleaned_name)
            path.rename(new_path)
            if new_path.is_file():
                files_cleaned += 1
            else:
                folders_cleaned += 1

    return files_cleaned, folders_cleaned


def remove_all_csvs(root: Path) -> int:
    """
    Remove _all.csv duplicates. Notion exports databases as both
    Name.csv (filtered view) and Name_all.csv (all rows).
    We keep _all.csv (more complete) and remove the filtered one,
    renaming _all.csv to drop the _all suffix.
    """
    removed = 0
    for all_csv in list(root.rglob("*_all.csv")):
        base_csv = all_csv.parent / all_csv.name.replace("_all.csv", ".csv")
        if base_csv.exists():
            base_csv.unlink()
            removed += 1
        # Rename _all.csv → .csv
        clean_name = all_csv.name.replace("_all.csv", ".csv")
        target = resolve_conflicts(all_csv.parent / clean_name)
        all_csv.rename(target)
    return removed


def build_database_registry(root: Path) -> dict[Path, list[str]]:
    """
    Scan for CSV files that represent Notion databases and map each
    database folder to its list of property names (from CSV headers).

    Notion exports a database as:
      - ParentFolder/DatabaseName <id>.csv          (filtered view)
      - ParentFolder/DatabaseName <id>_all.csv      (all rows)
      - ParentFolder/DatabaseName/Entry1 <id>.md    (one file per row)
      - ParentFolder/DatabaseName/Entry2 <id>.md

    The CSV and the folder share the same base name (before the ID).
    After cleaning, the folder name will have the ID stripped.

    Returns: {folder_path: [property_names_excluding_Name]}
    """
    registry = {}

    for csv_path in root.rglob("*.csv"):
        # Skip _all.csv — we use the regular CSV (or _all if regular doesn't exist)
        if "_all.csv" in csv_path.name:
            continue
        # Skip CSVs that aren't Notion databases (e.g., Stripe exports)
        # Notion database CSVs have a BOM and a "Name" column
        try:
            raw = csv_path.read_bytes()
            text = raw.decode("utf-8-sig")  # Handle BOM
            reader = csv.reader(io.StringIO(text))
            headers = next(reader, None)
        except (UnicodeDecodeError, OSError):
            continue

        if not headers or headers[0].strip() != "Name":
            continue

        # Properties are all columns except "Name" (which becomes the title/filename)
        properties = [h.strip() for h in headers[1:] if h.strip()]

        if not properties:
            continue

        # Find the matching folder: same parent, same base name (before Notion ID)
        csv_stem = csv_path.stem  # e.g., "#JFDI 8f2fb47d8d79400e96243c1c411716dc"
        cleaned_stem = NOTION_ID_IN_NAME.sub("", csv_stem).strip()

        # Look for a sibling folder with matching name (with or without ID)
        parent = csv_path.parent
        for candidate in parent.iterdir():
            if not candidate.is_dir():
                continue
            candidate_clean = NOTION_ID_IN_NAME.sub("", candidate.name).strip()
            if candidate_clean == cleaned_stem:
                registry[candidate] = properties
                break

    return registry


def add_yaml_frontmatter(root: Path) -> int:
    """
    For markdown files that are entries in a Notion database, extract the
    property lines from the top of the file and convert them to YAML
    frontmatter.

    Before:
        # Fix Security Issues

        Scope: StandupBot
        Bucket: Internal
        Status: Not started

        ## About this project
        ...

    After:
        ---
        title: Fix Security Issues
        Scope: StandupBot
        Bucket: Internal
        Status: Not started
        ---

        ## About this project
        ...
    """
    registry = build_database_registry(root)

    if not registry:
        return 0

    converted = 0

    for db_folder, properties in registry.items():
        # Process all .md files directly inside this database folder
        for md_file in db_folder.iterdir():
            if not md_file.is_file() or md_file.suffix != ".md":
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            lines = text.split("\n")

            # Parse: expect "# Title", blank line, then "Key: Value" lines
            if not lines or not lines[0].startswith("# "):
                continue

            title = lines[0][2:].strip()

            # Find property lines after the title
            frontmatter = {"title": title}
            property_end_idx = 1
            found_properties = False

            # Skip blank lines after title
            idx = 1
            while idx < len(lines) and lines[idx].strip() == "":
                idx += 1

            # Collect Key: Value lines that match known database properties
            prop_names_lower = {p.lower(): p for p in properties}

            while idx < len(lines):
                line = lines[idx].strip()
                if not line:
                    # Blank line after properties = end of property block
                    if found_properties:
                        idx += 1
                        break
                    idx += 1
                    continue

                # Check if this line is "Key: Value" matching a known property
                colon_pos = line.find(":")
                if colon_pos > 0:
                    key = line[:colon_pos].strip()
                    value = line[colon_pos + 1:].strip()
                    if key.lower() in prop_names_lower:
                        # Use the original property name casing from CSV
                        original_key = prop_names_lower[key.lower()]
                        frontmatter[original_key] = value
                        found_properties = True
                        idx += 1
                        continue

                # Not a property line — stop
                break

            property_end_idx = idx

            if not found_properties:
                continue

            # Build YAML frontmatter
            yaml_lines = ["---"]
            # Title first
            yaml_lines.append(f"title: \"{_yaml_escape(title)}\"")
            # Then properties in CSV column order
            for prop in properties:
                if prop in frontmatter:
                    value = frontmatter[prop]
                    # Clean property key: strip emojis
                    clean_key = _strip_emojis(prop)
                    if not clean_key:
                        continue  # Skip properties that are only emojis
                    # Convert date-like values to ISO format
                    if value:
                        iso_value = _to_iso_date(value)
                        if iso_value != value:
                            # Dates don't need quotes in YAML
                            yaml_lines.append(f"{clean_key}: {iso_value}")
                        else:
                            yaml_lines.append(f"{clean_key}: \"{_yaml_escape(value)}\"")
                    else:
                        yaml_lines.append(f"{clean_key}: \"\"")
            yaml_lines.append("---")
            yaml_lines.append("")

            # Rebuild the file: frontmatter + remaining content (skip old title + properties)
            remaining_lines = lines[property_end_idx:]

            # Strip leading blank lines from remaining content
            while remaining_lines and remaining_lines[0].strip() == "":
                remaining_lines = remaining_lines[1:]

            new_text = "\n".join(yaml_lines) + "\n".join(remaining_lines)

            md_file.write_text(new_text, encoding="utf-8")
            converted += 1

    return converted


def _yaml_escape(value: str) -> str:
    """Escape special characters for YAML double-quoted strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _strip_emojis(text: str) -> str:
    """Remove emoji characters and clean up resulting whitespace."""
    # Remove characters in emoji-related Unicode categories
    cleaned = "".join(
        c for c in text
        if unicodedata.category(c) not in (
            "So",  # Symbol, other (most emojis)
            "Sk",  # Symbol, modifier (skin tones, etc.)
            "Cn",  # Not assigned (some emoji components)
        )
        and not (0x1F000 <= ord(c) <= 0x1FFFF)   # Supplemental symbols & emoticons
        and not (0x2600 <= ord(c) <= 0x27BF)      # Misc symbols & dingbats
        and not (0xFE00 <= ord(c) <= 0xFE0F)      # Variation selectors
        and not (0x200D == ord(c))                 # Zero-width joiner
    )
    # Collapse multiple spaces left behind
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


# Notion date formats to try parsing
_NOTION_DATE_FORMATS = [
    "%B %d, %Y %I:%M %p",     # "October 13, 2022 6:09 PM"
    "%B %d, %Y %I:%M:%S %p",  # "October 13, 2022 6:09:00 PM"
    "%B %d, %Y",               # "October 13, 2022"
    "%b %d, %Y %I:%M %p",     # "Oct 13, 2022 6:09 PM"
    "%b %d, %Y",               # "Oct 13, 2022"
]


def _to_iso_date(value: str) -> str:
    """
    Convert a Notion date string to ISO 8601 format.
    Returns the original string if it can't be parsed.
    """
    value = value.strip()
    for fmt in _NOTION_DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            # If the format included time, return datetime; otherwise just date
            if "%I" in fmt or "%H" in fmt:
                return dt.strftime("%Y-%m-%dT%H:%M")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def generate_obsidian_bases(root: Path) -> int:
    """
    Create an Obsidian .base file for each Notion database.

    The .base file sits next to the database folder and creates a table
    view of all markdown files in that folder, using frontmatter properties
    as columns.

    Uses the *cleaned* folder and property names (IDs stripped, emojis removed).
    Must be called AFTER name cleaning and frontmatter generation.
    """
    created = 0

    # Find database folders: folders that have a sibling CSV with matching name
    for csv_path in root.rglob("*.csv"):
        # Read CSV to check if it's a Notion database (has "Name" as first col)
        try:
            raw = csv_path.read_bytes()
            text = raw.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            headers = next(reader, None)
        except (UnicodeDecodeError, OSError):
            continue

        if not headers or headers[0].strip() != "Name":
            continue

        # Find matching folder (same name as CSV, without extension)
        db_folder = csv_path.parent / csv_path.stem
        if not db_folder.is_dir():
            continue

        # Get the property names (cleaned: emojis stripped)
        properties = []
        for h in headers[1:]:
            h = h.strip()
            if not h:
                continue
            clean_h = _strip_emojis(h)
            if clean_h:
                properties.append(clean_h)

        # Determine the folder path relative to root for the filter
        rel_folder = db_folder.relative_to(root)
        folder_str = str(rel_folder).replace("\\", "/")

        # Build the .base YAML content
        lines = []

        # Filters: only markdown files in this folder
        lines.append("filters:")
        lines.append("  and:")
        lines.append(f'    - file.inFolder("{folder_str}")')
        lines.append('    - \'file.ext == "md"\'')

        # Views
        lines.append("")
        lines.append("views:")
        lines.append("  - type: table")
        lines.append(f'    name: "{csv_path.stem}"')

        # Column order: file name first, then properties
        lines.append("    order:")
        lines.append("      - file.name")
        for prop in properties:
            lines.append(f"      - {prop}")

        base_content = "\n".join(lines) + "\n"

        # Write the .base file next to the folder
        base_path = csv_path.parent / f"{csv_path.stem}.base"
        base_path.write_text(base_content, encoding="utf-8")
        created += 1

    return created


def update_internal_links(root: Path) -> int:
    """Rewrite markdown links to match the cleaned filenames."""
    count = 0
    for md_file in root.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        def replace_link(match):
            nonlocal count
            prefix = match.group(1)
            link_path = match.group(2)
            suffix = match.group(3)

            if link_path.startswith(("http://", "https://", "#", "mailto:")):
                return match.group(0)

            # Clean each path segment, and drop pure-ID segments
            parts = link_path.split("/")
            cleaned_parts = []
            for part in parts:
                if is_pure_id_folder(part):
                    continue  # Skip pure hex-ID path segments
                cleaned_parts.append(clean_filename(part))

            cleaned = "/".join(cleaned_parts)
            if cleaned != link_path:
                count += 1
                return f"{prefix}{cleaned}{suffix}"
            return match.group(0)

        new_text = re.sub(
            r"(\[(?:[^\]]*)\]\()([^)]+)(\))",
            replace_link,
            text,
        )

        if new_text != text:
            md_file.write_text(new_text, encoding="utf-8")

    return count


def flatten_wrapper(output_dir: Path) -> None:
    """
    Flatten top-level wrapper folders:
    1. The Export-UUID folder Notion always creates
    2. Any remaining single-child folder
    """
    # First: flatten Export-UUID wrapper
    for child in list(output_dir.iterdir()):
        if child.is_dir() and EXPORT_WRAPPER.match(child.name):
            for item in child.iterdir():
                target = resolve_conflicts(output_dir / item.name)
                item.rename(target)
            child.rmdir()
            break

    # Then: if only one child folder remains, flatten it too
    children = list(output_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        wrapper = children[0]
        for item in wrapper.iterdir():
            target = resolve_conflicts(output_dir / item.name)
            item.rename(target)
        wrapper.rmdir()


def remove_index_html(root: Path) -> bool:
    """Remove the index.html Notion includes at the root."""
    index = root / "index.html"
    if index.exists():
        index.unlink()
        return True
    return False


def process_zip(zip_path: str, output_dir: str, keep_all_csv: bool = False, add_frontmatter: bool = True) -> None:
    """Extract and clean a Notion export zip."""
    zip_path = Path(zip_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()

    if not zip_path.exists():
        print(f"Error: '{zip_path}' not found.")
        return

    if not zipfile.is_zipfile(zip_path):
        print(f"Error: '{zip_path}' is not a valid zip file.")
        return

    # Work in a temp directory first
    temp_dir = output_dir.parent / f".{output_dir.name}_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    print(f"Extracting '{zip_path.name}'...")
    extract_nested_zips(zip_path, temp_dir)

    # Step 1: Flatten the Export-UUID wrapper
    print("Flattening wrapper folders...")
    flatten_wrapper(temp_dir)

    # Step 2: Remove index.html
    remove_index_html(temp_dir)

    # Step 3: Collapse pure hex-ID intermediate folders
    print("Collapsing ID-only folders...")
    collapsed = collapse_id_folders(temp_dir)

    # Step 4: Handle _all.csv duplicates
    csv_removed = 0
    if not keep_all_csv:
        print("Deduplicating CSV exports...")
        csv_removed = remove_all_csvs(temp_dir)

    # Step 5: Add YAML frontmatter to database entries (before name cleaning)
    frontmatter_added = 0
    if add_frontmatter:
        print("Adding YAML frontmatter to database entries...")
        frontmatter_added = add_yaml_frontmatter(temp_dir)

    # Step 6: Strip Notion IDs from names
    print("Cleaning filenames...")
    files_cleaned, folders_cleaned = clean_names(temp_dir)

    # Step 7: Fix internal markdown links
    print("Updating internal links...")
    links_updated = update_internal_links(temp_dir)

    # Step 8: Generate Obsidian .base files for each database
    bases_created = 0
    if add_frontmatter:  # Bases only make sense if frontmatter was added
        print("Generating Obsidian .base files...")
        bases_created = generate_obsidian_bases(temp_dir)

    # Move temp to final destination
    if output_dir.exists():
        shutil.rmtree(output_dir)
    temp_dir.rename(output_dir)

    # Summary
    total_md = list(output_dir.rglob("*.md"))
    total_csv = list(output_dir.rglob("*.csv"))
    total_base = list(output_dir.rglob("*.base"))
    total_other = [p for p in output_dir.rglob("*") if p.is_file() and p.suffix not in (".md", ".csv", ".base")]
    total_folders = [p for p in output_dir.rglob("*") if p.is_dir()]

    print()
    print("Done!")
    print(f"  Output:            {output_dir}")
    print(f"  Markdown files:    {len(total_md)}")
    print(f"  CSV files:         {len(total_csv)}")
    print(f"  Base files:        {len(total_base)}")
    print(f"  Other files:       {len(total_other)} (images, PDFs, etc.)")
    print(f"  Folders:           {len(total_folders)}")
    print(f"  ID folders removed:{collapsed}")
    print(f"  Names cleaned:     {files_cleaned} files, {folders_cleaned} folders")
    print(f"  CSV deduped:       {csv_removed}")
    print(f"  Frontmatter added: {frontmatter_added}")
    print(f"  Bases created:     {bases_created}")
    print(f"  Links updated:     {links_updated}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up a Notion Markdown & CSV export into a tidy folder structure.",
    )
    parser.add_argument(
        "zipfile",
        help="Path to the Notion export .zip file",
    )
    parser.add_argument(
        "--output", "-o",
        default="./notion-export",
        help="Output folder (default: ./notion-export)",
    )
    parser.add_argument(
        "--keep-all-csv",
        action="store_true",
        help="Keep both Name.csv and Name_all.csv (default: merge to single .csv)",
    )
    parser.add_argument(
        "--no-frontmatter",
        action="store_true",
        help="Skip adding YAML frontmatter to database entry markdown files",
    )
    args = parser.parse_args()
    process_zip(
        args.zipfile,
        args.output,
        keep_all_csv=args.keep_all_csv,
        add_frontmatter=not args.no_frontmatter,
    )


if __name__ == "__main__":
    main()
