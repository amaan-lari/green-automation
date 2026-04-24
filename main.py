"""
main.py — Async orchestrator for greendotball.com bulk registration.

Usage
-----
Dry-run (prints plan, nothing submitted):
    python main.py --count 100 --dry-run

Live run (default batch-size = 10):
    python main.py --count 200

Live run with custom batch-size and visible browser:
    python main.py --count 50 --batch-size 5 --no-headless

Resume (skip phone numbers already in the DB):
    python main.py --count 200 --resume

Flow
----
1. Generate `count` unique Indian phone numbers.
2. Generate `count` green-circle images (images/image_N.png).
3. Split into batches of `batch_size`.
4. For each batch, run RegistrationBot sequentially (2-s delay is inside the bot).
5. Persist every result to SQLite via RegistrationDB.
6. Print a live progress line that overwrites itself in-place.
7. On finish, print a summary report and export two CSVs.
8. Always clean up the images/ folder after the run.
"""

import argparse
import asyncio
import logging
import sys
import time
from typing import List, Tuple

from database import RegistrationDB
from generate_images import cleanup_images, generate_images_batch
from generate_numbers import generate_indian_phone_numbers
from register import RegistrationBot


# ── Logging setup ──────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("automation")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — full detail
    fh = logging.FileHandler("automation.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO and above only
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = _setup_logging()


# ── Progress printer ───────────────────────────────────────────────────────────

class Progress:
    """Prints an overwriting progress line to stdout."""

    def __init__(self, total: int) -> None:
        self.total     = total
        self.processed = 0
        self.success   = 0
        self.failed    = 0
        self._start    = time.monotonic()

    def update(self, status: str) -> None:
        self.processed += 1
        if status == "success":
            self.success += 1
        else:
            self.failed += 1
        self._print()

    def _print(self) -> None:
        elapsed = time.monotonic() - self._start
        rate    = self.processed / elapsed if elapsed > 0 else 0
        eta_s   = (self.total - self.processed) / rate if rate > 0 else 0
        eta_str = _fmt_seconds(eta_s) if self.processed < self.total else "done"

        line = (
            f"  Processed {self.processed}/{self.total}"
            f" | Success: {self.success}"
            f" | Failed: {self.failed}"
            f" | ETA: {eta_str}"
        )
        # Overwrite the current line; pad to 80 chars so stale text is cleared
        sys.stdout.write(f"\r{line:<80}")
        sys.stdout.flush()

    def finish(self) -> None:
        self._print()
        print()   # move to next line after the final overwrite


def _fmt_seconds(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m{s:02d}s"


# ── Dry-run printer ────────────────────────────────────────────────────────────

def _print_dry_run_plan(
    phones: List[str],
    images: List[str],
    batch_size: int,
) -> None:
    total   = len(phones)
    batches = (total + batch_size - 1) // batch_size

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║               DRY-RUN  —  nothing will be submitted      ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Registrations : {total}")
    print(f"║  Batch size    : {batch_size}  ({batches} batch{'es' if batches != 1 else ''})")
    print(f"║  Delay between : 2.0 s per attempt")
    print(f"║  Est. duration : ~{_fmt_seconds(total * 2.0)}")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  First 10 phone + image pairs:")
    for phone, img in zip(phones[:10], images[:10]):
        print(f"║    {phone}  →  {img}")
    if total > 10:
        print(f"║    … and {total - 10} more")
    print("╚══════════════════════════════════════════════════════════╝")
    print()


# ── Core orchestrator ──────────────────────────────────────────────────────────

async def run(
    count:      int,
    batch_size: int,
    dry_run:    bool,
    headless:   bool,
    resume:     bool,
) -> None:

    log.info("Run started — count=%d  batch_size=%d  dry_run=%s  resume=%s",
             count, batch_size, dry_run, resume)

    images: List[str] = []

    try:
        # ── 1. Optionally skip already-attempted numbers ───────────────
        skip_phones: set = set()
        if resume:
            db_check = RegistrationDB()
            skip_phones = db_check.get_exhausted_phones(max_uses=10)
            if skip_phones:
                log.info(
                    "--resume: skipping %d number(s) already used 10+ times",
                    len(skip_phones),
                )
            else:
                log.info("--resume: no exhausted numbers found, nothing to skip")

        # ── 2. Generate phones and images ──────────────────────────────
        log.info("Generating phone numbers…")
        all_phones: List[str] = generate_indian_phone_numbers(count + len(skip_phones))
        phones: List[str] = [p for p in all_phones if p not in skip_phones][:count]
        log.info("Generated %d phone number(s) (%d skipped via --resume)",
                 len(phones), len(all_phones) - len(phones))

        if not phones:
            log.warning("No new phone numbers to process after applying --resume filter.")
            return

        log.info("Generating %d image(s)…", len(phones))
        images = generate_images_batch(len(phones))
        log.info("Images written to: %s", images[0].rsplit("/", 1)[0] if images else "—")

        pairs: List[Tuple[str, str]] = list(zip(phones, images))

        # ── 3. Dry-run short-circuit ───────────────────────────────────
        if dry_run:
            _print_dry_run_plan(phones, images, batch_size)
            log.info("Dry-run: exercising RegistrationBot on pair #1 for selector detail")
            bot    = RegistrationBot(headless=headless, dry_run=True)
            result = await bot.register(phones[0], images[0])
            log.info("Bot dry-run result: %s", result)
            print("Bot result:", result)
            return

        # ── 4. Live run ────────────────────────────────────────────────
        db       = RegistrationDB()
        bot      = RegistrationBot(headless=headless, dry_run=False)
        progress = Progress(total=len(phones))

        log.info("Starting live registrations in batches of %d…", batch_size)

        batches = [pairs[i : i + batch_size] for i in range(0, len(pairs), batch_size)]

        for batch_idx, batch in enumerate(batches):
            log.debug("Batch %d/%d — %d pair(s)", batch_idx + 1, len(batches), len(batch))
            for phone, image_path in batch:
                try:
                    result = await bot.register(phone, image_path)
                except Exception as exc:
                    result = {"status": "failed", "message": f"Unhandled exception: {exc}"}

                status  = result.get("status", "failed")
                message = result.get("message", "")

                db.save_result(
                    phone=phone,
                    image=image_path,
                    status=status,
                    error=None if status == "success" else message,
                )

                log.debug("%-15s  %-8s  %s", phone, status.upper(), message)
                progress.update(status)

        progress.finish()

        # ── 5. Summary + CSV export ────────────────────────────────────
        log.info("Exporting results…")
        success_csv = db.export_successful_numbers_csv()
        failed_csv  = db.export_failed_numbers_csv()
        log.info("Successful numbers → %s", success_csv)
        log.info("Failed numbers     → %s", failed_csv)

        summary = db.get_summary()
        log.info(
            "Run complete — attempted=%d  success=%d  failed=%d",
            summary["total_attempted"],
            summary["total_success"],
            summary["total_failed"],
        )

        print()
        db.print_summary_report()

    finally:
        # ── 6. Always clean up images ──────────────────────────────────
        if images:
            log.info("Cleaning up images folder…")
            cleanup_images()
            log.info("Images folder removed.")
        log.info("Run finished.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Bulk registration orchestrator for greendotball.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --count 100 --dry-run\n"
            "  python main.py --count 200\n"
            "  python main.py --count 50 --batch-size 5 --no-headless\n"
            "  python main.py --count 200 --resume\n"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of registrations to attempt (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        dest="batch_size",
        help="Registrations per batch (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print plan without submitting anything",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        dest="no_headless",
        help="Show browser windows (useful for debugging)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        dest="resume",
        help="Skip phone numbers already recorded in the database",
    )

    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    return args


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        run(
            count      = args.count,
            batch_size = args.batch_size,
            dry_run    = args.dry_run,
            headless   = not args.no_headless,
            resume     = args.resume,
        )
    )
