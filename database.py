import csv
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "registrations.db")


class RegistrationDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS registrations (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number  TEXT    NOT NULL,
                    image_path    TEXT    NOT NULL,
                    status        TEXT    NOT NULL CHECK(status IN ('success', 'failed')),
                    error_message TEXT,
                    timestamp     TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS summary (
                    id               INTEGER PRIMARY KEY CHECK(id = 1),
                    total_attempted  INTEGER NOT NULL DEFAULT 0,
                    total_success    INTEGER NOT NULL DEFAULT 0,
                    total_failed     INTEGER NOT NULL DEFAULT 0,
                    last_updated     TEXT    NOT NULL
                );

                INSERT OR IGNORE INTO summary (id, total_attempted, total_success, total_failed, last_updated)
                VALUES (1, 0, 0, 0, CURRENT_TIMESTAMP);
            """)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_result(
        self,
        phone: str,
        image: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Insert a registration result and update the summary row."""
        if status not in ("success", "failed"):
            raise ValueError(f"status must be 'success' or 'failed', got: {status!r}")

        timestamp = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO registrations (phone_number, image_path, status, error_message, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (phone, image, status, error, timestamp),
            )
            conn.execute(
                f"""
                UPDATE summary SET
                    total_attempted = total_attempted + 1,
                    total_success   = total_success   + {'1' if status == 'success' else '0'},
                    total_failed    = total_failed    + {'1' if status == 'failed'  else '0'},
                    last_updated    = ?
                WHERE id = 1
                """,
                (timestamp,),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict:
        """Return the summary row as a plain dict."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM summary WHERE id = 1").fetchone()
        return dict(row)

    def get_attempted_phones(self) -> set:
        """Return the set of all phone numbers that have been attempted."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT phone_number FROM registrations"
            ).fetchall()
        return {row["phone_number"] for row in rows}

    def get_exhausted_phones(self, max_uses: int = 10) -> set:
        """
        Return phone numbers that have already been used `max_uses` or more
        times.  Numbers below the threshold can still be reused (each time
        with a different image).
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT phone_number
                FROM   registrations
                GROUP  BY phone_number
                HAVING COUNT(*) >= ?
                """,
                (max_uses,),
            ).fetchall()
        return {row["phone_number"] for row in rows}

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_csv(self, status: str, filename: str) -> str:
        """Write phone numbers (+ timestamp) for *status* rows to a CSV file."""
        output_dir = os.path.dirname(self.db_path)
        filepath = os.path.join(output_dir, filename)

        with self._connect() as conn:
            rows: List[sqlite3.Row] = conn.execute(
                """
                SELECT phone_number, image_path, timestamp
                FROM   registrations
                WHERE  status = ?
                ORDER  BY timestamp
                """,
                (status,),
            ).fetchall()

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["phone_number", "image_path", "timestamp"])
            for row in rows:
                writer.writerow([row["phone_number"], row["image_path"], row["timestamp"]])

        return filepath

    def export_successful_numbers_csv(self) -> str:
        """Export all successful registrations to successful_numbers.csv."""
        return self._export_csv("success", "successful_numbers.csv")

    def export_failed_numbers_csv(self) -> str:
        """Export all failed registrations to failed_numbers.csv."""
        return self._export_csv("failed", "failed_numbers.csv")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def print_summary_report(self) -> None:
        """Print a formatted summary of registration results."""
        s = self.get_summary()
        attempted = s["total_attempted"]
        success   = s["total_success"]
        failed    = s["total_failed"]
        updated   = s["last_updated"]

        success_pct = (success / attempted * 100) if attempted else 0.0
        failed_pct  = (failed  / attempted * 100) if attempted else 0.0

        print("=" * 40)
        print("     REGISTRATION SUMMARY REPORT")
        print("=" * 40)
        print(f"  Total attempted : {attempted}")
        print(f"  Successful      : {success}  ({success_pct:.1f}%)")
        print(f"  Failed          : {failed}  ({failed_pct:.1f}%)")
        print(f"  Last updated    : {updated}")
        print("=" * 40)
