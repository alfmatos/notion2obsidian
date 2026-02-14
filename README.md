# notion2obsidian

A Python CLI tool that converts a Notion "Markdown & CSV" export into a clean, Obsidian-compatible vault.

Notion exports are cluttered with 32-character hex IDs in every filename, nested wrapper folders, duplicate CSVs, and raw property lines instead of proper frontmatter. This tool fixes all of that in one pass.

## What it does

- **Extracts nested zips** — handles Notion's zip-of-zips pattern for large exports
- **Flattens wrapper folders** — removes the `Export-UUID/` directory Notion creates
- **Collapses ID-only folders** — intermediate folders that are just hex IDs get removed, children moved up
- **Deduplicates CSVs** — keeps the complete `_all.csv` version, drops the filtered one
- **Adds YAML frontmatter** — converts Notion's `Key: Value` property lines into proper YAML frontmatter with ISO 8601 dates and emoji-free keys
- **Cleans filenames** — strips 32-char hex IDs from every file and folder name
- **Updates internal links** — rewrites markdown links to match the cleaned paths
- **Generates `.base` files** — creates Obsidian database views for each Notion database

### Before

```
Export-abc123/
  #JFDI 8f2fb47d8d79400e96243c1c411716dc/
    Fix Bugs a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6.md
  #JFDI 8f2fb47d8d79400e96243c1c411716dc.csv
  #JFDI 8f2fb47d8d79400e96243c1c411716dc_all.csv
```

### After

```
#JFDI/
  Fix Bugs.md       (with YAML frontmatter)
#JFDI.csv
#JFDI.base           (Obsidian database view)
```

## Installation

No dependencies required — uses only the Python standard library.

```bash
git clone https://github.com/alfmatos/notion2obsidian.git
cd notion2obsidian
```

Requires Python 3.10+.

## Usage

```bash
python3 notion2obsidian.py <export.zip> [--output <folder>] [--keep-all-csv] [--no-frontmatter]
```

### Examples

```bash
# Basic usage — output goes to ./notion-export
python3 notion2obsidian.py ~/Downloads/Export-2026-02-14.zip

# Specify output folder
python3 notion2obsidian.py export.zip --output ~/obsidian-vault

# Keep both filtered and complete CSV files
python3 notion2obsidian.py export.zip --keep-all-csv

# Skip YAML frontmatter generation
python3 notion2obsidian.py export.zip --no-frontmatter
```

### Options

| Flag | Description |
|------|-------------|
| `--output`, `-o` | Output folder (default: `./notion-export`) |
| `--keep-all-csv` | Keep both `Name.csv` and `Name_all.csv` instead of deduplicating |
| `--no-frontmatter` | Skip adding YAML frontmatter and generating `.base` files |

## How Notion exports work

When you export a Notion workspace as "Markdown & CSV", you get:

- Every page as a `.md` file with a 32-char hex ID appended to its name
- Databases as both a filtered `.csv` and a complete `_all.csv`
- Database entries as markdown files with `Key: Value` property lines at the top (not YAML)
- Nested folders, some of which are just hex IDs with no readable name
- An `Export-UUID/` wrapper folder at the root
- For large exports, a zip-of-zips with `Part-N.zip` files inside

This tool handles all of these quirks automatically.

## License

MIT
