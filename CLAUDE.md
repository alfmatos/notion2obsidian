# notion2obsidian

Python CLI tool that converts a Notion "Markdown & CSV" export zip into a clean, Obsidian-compatible vault structure.

## What it does (in processing order)

1. **Extracts nested zips** — Notion wraps large exports in a zip-of-zips (Part-N.zip files inside an outer zip)
2. **Flattens the Export-UUID/ wrapper folder** Notion creates at the root
3. **Removes index.html** that Notion includes
4. **Collapses pure hex-ID intermediate folders** — folders that are just 32-char hex IDs with no readable name; their children are moved up one level
5. **Deduplicates CSV exports** — Notion exports databases as both `Name.csv` (filtered) and `Name_all.csv` (all rows); keeps the complete one, renames it to drop `_all`
6. **Adds YAML frontmatter to database entries** — reads CSV headers to identify database schemas, then extracts `Key: Value` property lines from the top of each markdown file and converts them to proper YAML frontmatter. Dates are converted to ISO 8601 format. Emojis are stripped from property keys but preserved in values.
7. **Strips 32-char hex Notion IDs from all filenames** — e.g. `Home e82f1f46f47e4859aef48d9da4875832.md` becomes `Home.md`
8. **Updates internal markdown links** to match cleaned filenames and collapsed folder paths
9. **Generates Obsidian .base files** for each Notion database — YAML files that create table views using `file.inFolder()` filters and frontmatter properties as columns

## Usage

```
python3 notion2obsidian.py <export.zip> [--output <folder>] [--keep-all-csv] [--no-frontmatter]
```

## Key architectural decisions

- Frontmatter is added **before** filename cleaning (so CSV-to-folder matching works with original Notion IDs)
- `.base` files are generated **after** filename cleaning (so folder paths in filters match the final structure)
- Database detection relies on CSVs having `Name` as the first column header (with BOM handling)
- No external dependencies — uses only the Python standard library

## Project structure

- `notion2obsidian.py` — single-file script, entire implementation
