from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import pandas as pd

from config import get_settings
from database.db import Database
from database.models import InstitutionDetail
from utils.delay import seconds_to_human
from utils.logger import get_logger

logger = get_logger(__name__)

EXPORT_COLUMNS: list[str] = [
    "title",
    "full_address",
    "email",
    "affiliations",
    "type",
    "established",
    "phone",
]


def export_all(db: Database, run_id: str) -> dict[str, Path]:
    cfg     = get_settings()
    t_start = time.monotonic()

    total = db.get_detail_count()
    logger.info(
        "Exporting for run_id=%r — %d records total", run_id, total
    )

    if total == 0:
        logger.warning("No records to export — skipping.")
        return {}

    rows: list[dict[str, Any]] = []
    for detail in db.iter_all_details(batch_size=500):
        rows.append(detail.to_export_dict())

    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
    logger.debug("DataFrame built: %d rows × %d cols", len(df), len(df.columns))

    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    csv_path = cfg.output_dir / f"{cfg.csv_filename}.csv"
    _export_csv(df, csv_path)
    paths["csv"] = csv_path

    xlsx_path = cfg.output_dir / f"{cfg.excel_filename}.xlsx"
    _export_xlsx_single(df, xlsx_path)
    paths["xlsx"] = xlsx_path

    xlsx_cat_path = cfg.output_dir / f"{cfg.excel_filename}_by_category.xlsx"
    college_rows = [d.to_export_dict() for d in db.iter_all_details(category="college", batch_size=500)]
    school_rows  = [d.to_export_dict() for d in db.iter_all_details(category="school",  batch_size=500)]
    df_college   = pd.DataFrame(college_rows, columns=EXPORT_COLUMNS)
    df_school    = pd.DataFrame(school_rows,  columns=EXPORT_COLUMNS)
    _export_xlsx_by_category(df, df_college, df_school, xlsx_cat_path)
    paths["xlsx_cat"] = xlsx_cat_path

    elapsed = time.monotonic() - t_start
    logger.info(
        "Export complete in %s — %d rows | %s | %s | %s",
        seconds_to_human(elapsed),
        len(df),
        csv_path.name,
        xlsx_path.name,
        xlsx_cat_path.name,
    )
    return paths


def export_csv_only(db: Database) -> Path:
    cfg  = get_settings()
    rows = [d.to_export_dict() for d in db.iter_all_details(batch_size=500)]
    df   = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
    path = cfg.output_dir / f"{cfg.csv_filename}.csv"
    _export_csv(df, path)
    return path


def _export_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(
        str(path),
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_NONNUMERIC,
        lineterminator="\n",
    )
    logger.info("CSV written: %s (%d rows)", path.name, len(df))


def _export_xlsx_single(df: pd.DataFrame, path: Path) -> None:
    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Institutions")
        _autosize_columns(writer.sheets["Institutions"], df)
        writer.sheets["Institutions"].freeze_panes = "A2"

    logger.info("Excel written: %s (%d rows)", path.name, len(df))


def _export_xlsx_by_category(
    df: pd.DataFrame,
    df_college: pd.DataFrame,
    df_school: pd.DataFrame,
    path: Path,
) -> None:
    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="All")
        _autosize_columns(writer.sheets["All"], df)
        writer.sheets["All"].freeze_panes = "A2"

        for subset, sheet_name in [(df_college, "Colleges"), (df_school, "Schools")]:
            if len(subset) > 0:
                subset.to_excel(writer, index=False, sheet_name=sheet_name)
                _autosize_columns(writer.sheets[sheet_name], subset)
                writer.sheets[sheet_name].freeze_panes = "A2"

    logger.info(
        "Excel by-category written: %s (all=%d colleges=%d schools=%d)",
        path.name, len(df), len(df_college), len(df_school),
    )


def _autosize_columns(worksheet: Any, df: pd.DataFrame) -> None:
    from openpyxl.utils import get_column_letter

    for col_idx, col_name in enumerate(df.columns, start=1):
        col_letter = get_column_letter(col_idx)

        max_len = len(str(col_name))
        for val in df[col_name]:
            if val is not None:
                cell_len = len(str(val))
                if cell_len > max_len:
                    max_len = cell_len

        adjusted = min(max_len + 2, 80)
        worksheet.column_dimensions[col_letter].width = adjusted
