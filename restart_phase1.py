import sys, sqlite3
sys.path.insert(0, ".")
from config import get_settings
from storage.checkpoint import delete as del_cp

cfg = get_settings()


conn = sqlite3.connect(str(cfg.db_path), timeout=30)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("DELETE FROM institution_slugs;")
conn.execute("DELETE FROM crawl_status;")
conn.commit()
slugs   = conn.execute("SELECT COUNT(*) FROM institution_slugs;").fetchone()[0]
details = conn.execute("SELECT COUNT(*) FROM institution_details;").fetchone()[0]
conn.close()
print(f"Slugs cleared : {slugs}  (should be 0)")
print(f"Details kept  : {details:,}  (22,133 preserved)")

del_cp("slug_discovery.json")
print("Checkpoint deleted")

print("\nRunning Phase 1 with new incremental slug_manager...")
from database.db import Database
from crawler.slug_manager import run_slug_discovery

with Database() as db:
    status = run_slug_discovery(db=db, run_id="fresh-phase1", force_restart=True)

print(f"\nPhase 1 done:")
print(f"  Slugs in DB : {status.total_slugs:,}")
print(f"  New inserted: {status.completed:,}")
if status.total_slugs >= 39000:
    print("\n  OK — run: python main.py --skip-phase1")
else:
    print(f"\n  WARNING: only {status.total_slugs:,} slugs. Retry.")
