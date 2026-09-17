"""Excel/CSV data import/export (Phase 8).

Import pipeline (`importer.run_import`): parse (`parsing.py`) -> map columns
(`column_mapping.py`) -> validate + resolve references (`validation.py`) -> detect duplicates
(`duplicates.py`) -> insert via the same `TaskCreate`/`task_service.create_task` path the CRUD
API uses. The same function drives both preview (dry run, nothing written) and commit (writes
tasks + one `ImportHistory` row).

Export (`export.py`): task-list and manager-dashboard-report export to CSV/XLSX.

`parsing.py` is the only format-aware module — see its docstring for how a future Google Sheets
source would plug in without touching mapping/validation/duplicates/importer/export.
"""

from app.services.import_export.importer import ImportResult, RowOutcome, run_import

__all__ = ["run_import", "ImportResult", "RowOutcome"]
