from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_manager_or_admin
from app.core.uploads import enforce_upload_size
from app.database.session import get_db
from app.models.user import User
from app.schemas.import_export import ImportHistorySchema, ImportResultSchema
from app.services.import_export import run_import
from app.services.import_export.history import get_history, list_history

router = APIRouter(prefix="/api/import", tags=["import-export"])


@router.post("/preview", response_model=ImportResultSchema)
async def preview_import(
    file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> ImportResultSchema:
    """Parse, map columns, validate, and check for duplicates — but write nothing to the
    database and log nothing to `import_history`. Call `/commit` with the same file to actually
    import; running the identical pipeline twice means the preview can't lie about what commit
    will do. Manager/admin only.
    """
    content = await file.read()
    enforce_upload_size(content)
    result = run_import(db, filename=file.filename or "upload", content=content, dry_run=True, imported_by=None)
    return ImportResultSchema.model_validate(result)


@router.post("/commit", response_model=ImportResultSchema)
async def commit_import(
    file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> ImportResultSchema:
    """Run the same pipeline as `/preview`, but actually create a `Task` for every accepted
    row and record one `import_history` row summarizing the run (including a file-level
    failure, e.g. an unreadable file or a missing required column — that's still an attempted
    import worth auditing, even though zero rows were processed). `imported_by` is always the
    real authenticated caller, never a client-supplied field.
    """
    content = await file.read()
    enforce_upload_size(content)
    result = run_import(
        db, filename=file.filename or "upload", content=content, dry_run=False, imported_by=current_user.id
    )
    return ImportResultSchema.model_validate(result)


@router.get("/history", response_model=list[ImportHistorySchema])
def list_import_history(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> list[ImportHistorySchema]:
    return [ImportHistorySchema.model_validate(h) for h in list_history(db, skip=skip, limit=limit)]


@router.get("/history/{history_id}", response_model=ImportHistorySchema)
def get_import_history(
    history_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> ImportHistorySchema:
    record = get_history(db, history_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import history record not found")
    return ImportHistorySchema.model_validate(record)
