# Archived one-off scripts

These scripts are historical one-time data migrations and fixers. They are
preserved here for git history and reference but **must not be run** against
the current data files — they hardcode obsolete state (old tag systems,
descriptions, ID lists, mojibake patterns) and would corrupt the dashboard.

The active ingest pipeline lives at the project root:

- `update.py` — daily federal-source scraper (called by `.github/workflows/daily-update.yml`)
- `update.ps1` — Windows-side manual scraper (parallel to `update.py`)
- `update_media.py` — daily media scraper (called by `.github/workflows/media-update.yml`)
- `enrich.py` — Claude-API enrichment for auto-fetched items
- `review_pending.py` — Claude-API review for staged media items
- `tag_allowlist.py` — canonical tag rules; all scripts that write tags must use this

## Schema rules (do not violate)

1. The `description` field is **never** written. The dashboard displays only
   title / link / date / agency / type / state / amount / tags.
2. Tags are restricted to the allowlist in `tag_allowlist.py` (programs +
   vulnerable fraud areas only). Any other tag is filtered out.

If you need to make a one-off change again, write a new script — do not
resurrect anything from this archive.
