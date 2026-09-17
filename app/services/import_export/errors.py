"""File-level import errors — problems with the upload as a whole (wrong file type, no data,
a required column that couldn't be mapped, too many rows) as opposed to a single row's data
being invalid. Row-level problems are never exceptions; they're collected as strings in
`RowOutcome.errors` (see `importer.py`) so one bad row doesn't abort the whole import.
"""


class ImportFileError(ValueError):
    """Base class for problems that prevent an import from starting at all."""


class UnsupportedFileTypeError(ImportFileError):
    pass


class EmptyFileError(ImportFileError):
    pass


class MissingRequiredColumnsError(ImportFileError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required column(s): {', '.join(missing)}")


class TooManyRowsError(ImportFileError):
    pass
