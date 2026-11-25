import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import Engine


class BackupError(Exception):
    """A backup or restore could not be completed safely."""


class BackupService:
    """Create and safely restore backups of a file-based SQLite database."""
    def __init__(self, engine: Engine):
        """Initialize the service for the SQLite database configured by engine."""
        if engine.url.get_backend_name() != "sqlite" or not engine.url.database:
            raise BackupError("Backup requires a file-based SQLite database.")
        if engine.url.database == ":memory:":
            raise BackupError("Backup requires a file-based SQLite database.")
        self.database = Path(engine.url.database).resolve()

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        """Open a SQLite database in read-only mode."""
        return sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )

    @staticmethod
    def _copy(source: sqlite3.Connection, destination: sqlite3.Connection) -> None:
        """Copy a database while allowing a bounded wait for SQLite locks."""
        deadline = time.monotonic() + 10

        def progress(status, _remaining, _total):
            if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                if time.monotonic() >= deadline:
                    raise BackupError(
                        "The database is busy. Close other instances and retry."
                    )

        source.backup(destination, pages=128, progress=progress, sleep=0.1)

    def _check_distinct(self, path: Path) -> None:
        """Reject a path that refers to the active database."""
        if path.resolve() == self.database or (
            path.exists() and self.database.exists() and path.samefile(self.database)
        ):
            raise BackupError("Choose a file other than the active database.")

    def create_backup(self, destination: Path) -> None:
        """Create a new backup file without overwriting an existing file."""
        destination = Path(destination)
        self._check_distinct(destination)
        try:
            with destination.open("xb"):
                pass
        except FileExistsError as exc:
            raise BackupError(
                "Backup file already exists. Choose a new filename."
            ) from exc
        try:
            with closing(self._connect_readonly(self.database)) as source:
                with closing(sqlite3.connect(destination, timeout=5)) as target:
                    self._copy(source, target)
        except (OSError, sqlite3.Error, BackupError):
            destination.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate(source: sqlite3.Connection, current: sqlite3.Connection) -> None:
        """Check backup integrity, foreign keys, and schema compatibility."""
        if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("The backup failed SQLite's integrity check.")
        if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("The backup contains invalid database references.")
        schema_query = (
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
        if source.execute(schema_query).fetchall() != (
            current.execute(schema_query).fetchall()
        ):
            raise BackupError(
                "The backup database schema is incompatible with this database."
            )

    def restore(self, backup: Path) -> Path:
        """Restore a compatible backup and return the safety-backup path."""
        backup = Path(backup)
        self._check_distinct(backup)
        fd, temp_name = tempfile.mkstemp(
            prefix="finance-restore-", suffix=".db", dir=self.database.parent
        )
        os.close(fd)
        staged = Path(temp_name)
        try:
            with closing(self._connect_readonly(backup)) as source:
                with closing(sqlite3.connect(staged, timeout=5)) as snapshot:
                    self._copy(source, snapshot)
            with closing(self._connect_readonly(staged)) as snapshot:
                with closing(self._connect_readonly(self.database)) as current:
                    self._validate(snapshot, current)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                safety = self.database.with_name(
                    f"{self.database.stem}-pre-restore-{stamp}-{uuid4().hex[:8]}.db"
                )
                self.create_backup(safety)
                try:
                    with closing(sqlite3.connect(self.database, timeout=5)) as current:
                        self._copy(snapshot, current)
                except (OSError, sqlite3.Error, BackupError) as exc:
                    raise BackupError(
                        f"Restore failed. The safety backup is at {safety}. {exc}"
                    ) from exc
            return safety
        finally:
            staged.unlink(missing_ok=True)
