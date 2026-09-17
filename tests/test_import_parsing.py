"""Unit tests for app.services.import_export.parsing and .column_mapping — pure, no database.
Covers both file formats and the file-level failure modes (unsupported type, empty file, no
data rows, too many rows) that abort an import before any row is even looked at.
"""

import io

import pytest
from openpyxl import Workbook

from app.services.import_export.column_mapping import map_columns
from app.services.import_export.errors import EmptyFileError, TooManyRowsError, UnsupportedFileTypeError
from app.services.import_export.parsing import parse_upload


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_csv_basic():
    content = b"Employee,Task,Project\nAlice,Design homepage,Website Revamp\n"
    parsed = parse_upload("tasks.csv", content)
    assert parsed.headers == ["Employee", "Task", "Project"]
    assert parsed.rows == [{"Employee": "Alice", "Task": "Design homepage", "Project": "Website Revamp"}]


def test_parse_csv_utf8_bom():
    content = "﻿Employee,Task,Project\nAlice,Design,Website\n".encode("utf-8")
    parsed = parse_upload("tasks.csv", content)
    assert parsed.headers[0] == "Employee"  # BOM stripped, not left glued to the first header


def test_parse_csv_ragged_row_padded_not_erroring():
    content = b"Employee,Task,Project\nAlice,Design\n"  # missing the Project cell
    parsed = parse_upload("tasks.csv", content)
    assert parsed.rows[0]["Project"] == ""


def test_parse_csv_no_data_rows_is_empty_file_error():
    content = b"Employee,Task,Project\n"
    with pytest.raises(EmptyFileError):
        parse_upload("tasks.csv", content)


def test_parse_csv_no_rows_at_all_is_empty_file_error():
    with pytest.raises(EmptyFileError):
        parse_upload("tasks.csv", b"")


def test_parse_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        parse_upload("tasks.txt", b"whatever")


def test_parse_legacy_xls_unsupported():
    with pytest.raises(UnsupportedFileTypeError):
        parse_upload("tasks.xls", b"whatever")


def test_parse_xlsx_basic():
    content = _xlsx_bytes([["Employee", "Task", "Project"], ["Alice", "Design homepage", "Website Revamp"]])
    parsed = parse_upload("tasks.xlsx", content)
    assert parsed.headers == ["Employee", "Task", "Project"]
    assert parsed.rows == [{"Employee": "Alice", "Task": "Design homepage", "Project": "Website Revamp"}]


def test_parse_xlsx_date_cell_becomes_iso_string():
    import datetime

    content = _xlsx_bytes(
        [["Employee", "Task", "Project", "Start Date"], ["Alice", "Design", "Website", datetime.date(2026, 8, 1)]]
    )
    parsed = parse_upload("tasks.xlsx", content)
    assert parsed.rows[0]["Start Date"] == "2026-08-01"


def test_parse_xlsx_no_data_rows_is_empty_file_error():
    content = _xlsx_bytes([["Employee", "Task", "Project"]])
    with pytest.raises(EmptyFileError):
        parse_upload("tasks.xlsx", content)


def test_parse_too_many_rows():
    rows = [["Employee", "Task", "Project"]] + [["A", f"Task {i}", "Project"] for i in range(5001)]
    content = _xlsx_bytes(rows)
    with pytest.raises(TooManyRowsError):
        parse_upload("tasks.xlsx", content)


# ------------------------------------------------------------------------------ column mapping ----


def test_map_columns_exact_headers():
    mapping = map_columns(["Employee", "Task", "Project", "Priority"])
    assert mapping.mapping["employee"] == "Employee"
    assert mapping.mapping["task"] == "Task"
    assert mapping.mapping["project"] == "Project"
    assert mapping.mapping["priority"] == "Priority"
    assert mapping.missing_required == []


def test_map_columns_alias_headers():
    mapping = map_columns(["Assigned To", "Task Title", "Project Name", "Est Hours", "Due Date"])
    assert mapping.mapping["employee"] == "Assigned To"
    assert mapping.mapping["task"] == "Task Title"
    assert mapping.mapping["project"] == "Project Name"
    assert mapping.mapping["estimated_hours"] == "Est Hours"
    assert mapping.mapping["deadline"] == "Due Date"


def test_map_columns_case_and_punctuation_insensitive():
    mapping = map_columns(["employee_name", "TASK-TITLE", "  Project  "])
    assert mapping.mapping["employee"] == "employee_name"
    assert mapping.mapping["task"] == "TASK-TITLE"
    assert mapping.mapping["project"] == "  Project  "


def test_map_columns_missing_required():
    mapping = map_columns(["Employee", "Priority"])
    assert set(mapping.missing_required) == {"task", "project"}


def test_map_columns_unmapped_optional_is_none():
    mapping = map_columns(["Task", "Project"])
    assert mapping.mapping["quality"] is None
    assert mapping.mapping["delay_reason"] is None
