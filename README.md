# EduSanjal Data Extraction Pipeline

A production-grade web scraper that collects structured data for every school and college listed on [edusanjal.com](https://edusanjal.com) — Nepal's largest education directory.

## What it does

Extracts 7 fields for every institution across two categories:

| Field | Description |
|---|---|
| `title` | Full institution name |
| `full_address` | Street / locality / city |
| `phone` | Contact / telephone numbers |
| `email` | Email addresses |
| `affiliations` | Affiliated universities or boards |
| `type` | Ownership type (Private, Public, Community…) |
| `established` | Year of establishment |

**Scale:** ~34,993 institutions — 1,464 colleges + 33,529 schools

**Method:** Pure REST API (`api.edusanjal.com.np/v1`) — no HTML parsing, no Selenium required in production.

## Output files

All files are written to `output/`:

| File | Contents |
|---|---|
| `institutions.csv` | All records, UTF-8, 7 columns |
| `institutions.xlsx` | All records, formatted Excel |
| `institutions_by_category.xlsx` | Separate sheets: All / Colleges / Schools |
| `edusanjal.db` | SQLite database with full pipeline state |

Missing values appear as `N/A` in all output files.

## Requirements

- Python 3.10+
- Google Chrome (for initial network inspection only — not needed for scraping)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Full run (recommended for first time)

```bash
python main.py
```

Runs Phase 1 (slug discovery) then Phase 2 (detail scraping). Takes ~3–4 hours for all 40K records.

### Resume after interruption

```bash
python main.py --skip-phase1
```

Skips slug discovery, resumes detail scraping from where it left off. Already-scraped records are skipped automatically.

### Slug discovery only

```bash
python main.py --skip-phase2
```

Discovers and stores all institution slugs without scraping details.

### Export existing data

```bash
python main.py --export-only
```

Re-exports whatever is currently in the database to CSV and Excel. No network calls.

### Full refresh (re-scrape everything)

```bash
python main.py --force-restart
```

Ignores all checkpoints and re-scrapes from page 1. Overwrites existing records.

### All options

```
--skip-phase1       Skip slug discovery (use slugs already in DB)
--skip-phase2       Skip detail scraping (discovery only)
--force-restart     Ignore checkpoints, start fresh
--workers N         Thread pool size (default: 8)
--batch-size N      Work queue window size (default: 50)
--progress-every N  Log progress every N records (default: 100)
--no-delay          Disable polite delays (dev/testing only)
--export-only       Re-export CSV/Excel from existing DB
```

## Architecture

```
main.py                         CLI entry point
├── workers/scheduler.py        Pipeline orchestrator
│
├── Phase 1 — Slug Discovery
│   ├── crawler/slug_manager.py         Orchestrates Phase 1
│   ├── crawler/college_slug_scraper.py 1,566 colleges / 66 pages
│   ├── crawler/school_slug_scraper.py  38,867 schools / 1,620 pages
│   └── crawler/pagination.py           Generic paginated API iterator
│
├── Phase 2 — Detail Scraping
│   ├── workers/queue_manager.py        Thread pool dispatch
│   ├── workers/worker.py               Per-record worker unit
│   ├── scraper/institution_scraper.py  fetch → parse → clean → validate → save
│   ├── scraper/api_client.py           HTTP client with retry
│   ├── scraper/parser.py               JSON field extractor
│   ├── scraper/cleaner.py              Data normalizer
│   └── scraper/validator.py            Advisory field validator
│
├── Database
│   ├── database/db.py                  Thread-safe data access layer
│   ├── database/models.py              SlugRecord / InstitutionDetail / CrawlStatus
│   └── database/migrations.py         Versioned schema migrations
│
├── Storage / Export
│   ├── storage/csv_export.py           CSV + Excel export
│   ├── storage/checkpoint.py           Crash-safe JSON checkpoints
│   └── storage/sqlite.py               Bulk persistence utilities
│
└── Utils
    ├── utils/session.py                requests.Session factory
    ├── utils/headers.py                User-Agent rotation
    ├── utils/delay.py                  Polite request throttling
    └── utils/logger.py                 Rotating file + console logging
```

## API endpoints used

```
Listing (slug discovery):
  GET https://api.edusanjal.com.np/v1/college/?page=N
  GET https://api.edusanjal.com.np/v1/school/?page=N

Detail (field extraction):
  GET https://api.edusanjal.com.np/v1/college/{slug}/
  GET https://api.edusanjal.com.np/v1/school/{slug}/
```

## Key features

- **Restartable** — checkpoint saves exact page position; re-run continues from where it stopped
- **Incremental CSV** — `institutions.csv` updated every 100 records during Phase 2
- **Safe Ctrl+C** — saves partial CSV before exiting, prints resume command
- **Thread-safe DB** — 8 concurrent workers with mutex-protected SQLite access
- **Fault tolerant** — up to 5 retries per record with exponential back-off (2, 4, 8, 16, 32s)
- **Polite crawling** — 0.8–2.5s random delay per request per worker

## Project structure

```
data scrapper/
├── main.py
├── config.py
├── requirements.txt
├── crawler/
├── scraper/
├── workers/
├── database/
├── storage/
├── utils/
├── output/          ← CSV, Excel, SQLite (git-ignored)
├── logs/            ← rotating log files (git-ignored)
└── checkpoints/     ← resume state (git-ignored)
```
