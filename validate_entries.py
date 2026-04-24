#!/usr/bin/env python3
"""
Entry validator for greendotball.com contest submissions.

Validation rules enforced:
  1. No duplicate submissions (by image hash or entry_id)
  2. Object must be green
  3. Object must be round
  4. Image must not be AI-generated
  5. Image must not be a stock image
  6. Phone number must be valid and non-suspicious

Runs automatically every 20-30 minutes (randomised).

DATA SOURCE
-----------
By default, `fetch_pending_entries()` reads from `entries_pending.csv`.
Replace that function body to pull from your own API / database.

Expected CSV columns (or dict keys from your API):
  entry_id, phone, image_url, timestamp

Set ANTHROPIC_API_KEY in your environment before running.
"""

import base64
import csv
import hashlib
import logging
import os
import random
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Set, Tuple

import anthropic
import phonenumbers
import requests
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LOG_FILE = "validation_log.csv"
PENDING_CSV = "entries_pending.csv"
PROCESSED_IDS_FILE = "processed_ids.txt"
MIN_INTERVAL_SECONDS = 20 * 60   # 20 minutes
MAX_INTERVAL_SECONDS = 30 * 60   # 30 minutes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("validator.log"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------

class ImageAnalysis(BaseModel):
    is_green: bool
    is_round: bool
    is_ai_generated: bool
    is_stock_image: bool
    confidence: str           # "high" | "medium" | "low"
    flag_for_manual_review: bool
    reasoning: str


# ---------------------------------------------------------------------------
# Image helper
# ---------------------------------------------------------------------------

def load_image_as_base64(source: str) -> Tuple[str, str]:
    """
    Return (base64_data, media_type) for a URL or local file path.
    Raises on failure.
    """
    ext_to_mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    if source.startswith("http://") or source.startswith("https://"):
        resp = requests.get(source, timeout=15)
        resp.raise_for_status()
        raw = resp.content
        # Try to infer media type from Content-Type header first
        ct = resp.headers.get("Content-Type", "")
        if "jpeg" in ct or "jpg" in ct:
            media_type = "image/jpeg"
        elif "png" in ct:
            media_type = "image/png"
        elif "gif" in ct:
            media_type = "image/gif"
        elif "webp" in ct:
            media_type = "image/webp"
        else:
            # Fall back to URL extension
            ext = Path(source.split("?")[0]).suffix.lower()
            media_type = ext_to_mime.get(ext, "image/jpeg")
    else:
        path = Path(source)
        raw = path.read_bytes()
        ext = path.suffix.lower()
        media_type = ext_to_mime.get(ext, "image/jpeg")

    return base64.standard_b64encode(raw).decode(), media_type


def image_sha256(source: str) -> Optional[str]:
    """Return SHA-256 hash of the image bytes, or None on failure."""
    try:
        if source.startswith("http://") or source.startswith("https://"):
            resp = requests.get(source, timeout=15)
            resp.raise_for_status()
            raw = resp.content
        else:
            raw = Path(source).read_bytes()
        return hashlib.sha256(raw).hexdigest()
    except Exception as exc:
        log.warning("Could not hash image %s: %s", source, exc)
        return None


# ---------------------------------------------------------------------------
# Phone validator
# ---------------------------------------------------------------------------

def validate_phone(raw_phone: str) -> Tuple[bool, str]:
    """
    Return (is_valid, reason).
    Checks parsability, line type (no premium-rate), and obvious fake patterns.
    """
    try:
        # Try without region first; fall back to assuming US/international
        try:
            parsed = phonenumbers.parse(raw_phone)
        except phonenumbers.NumberParseException:
            parsed = phonenumbers.parse(raw_phone, "US")

        if not phonenumbers.is_valid_number(parsed):
            return False, "Phone number is invalid"

        if not phonenumbers.is_possible_number(parsed):
            return False, "Phone number length is impossible"

        # Reject premium-rate / unknown line types
        line_type = phonenumbers.number_type(parsed)
        suspicious_types = {
            phonenumbers.PhoneNumberType.PREMIUM_RATE,
            phonenumbers.PhoneNumberType.UNKNOWN,
        }
        if line_type in suspicious_types:
            return False, f"Suspicious line type: {line_type.name}"

        # Check for obvious fakes using subscriber digits only (excludes country code)
        subscriber_digits = phonenumbers.national_significant_number(parsed)
        if len(set(subscriber_digits)) == 1:
            return False, "Phone number contains only one repeated digit (likely fake)"

        # Sequential ascending/descending (e.g. 0123456789, 1234567890, 9876543210)
        # Use a wrap-around string so we catch sequences that start mid-cycle
        # without matching partial runs like 7654321098
        if subscriber_digits in "01234567890" or subscriber_digits in "98765432109":
            return False, "Phone number appears to be a sequential dummy number"

        return True, "OK"

    except Exception as exc:
        return False, f"Could not parse phone number: {exc}"


# ---------------------------------------------------------------------------
# Claude-based image analyser
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a strict contest entry validator for a competition called "Green Dot Ball".

Your job is to analyse a submitted photo against four criteria and return a JSON decision.
Be strict but fair. When genuinely uncertain, set flag_for_manual_review to true rather than
outright rejecting.

Criteria:
1. IS_GREEN  – The main/focal object in the image must be predominantly green in colour.
2. IS_ROUND  – The main/focal object must be round or spherical in shape.
3. IS_AI_GENERATED – Flag images that show telltale signs of AI generation:
   - Unnatural textures, impossible lighting, blurred backgrounds with perfect subjects,
     suspiciously perfect geometry, or watermarks from AI platforms.
4. IS_STOCK_IMAGE – Flag images that appear to be stock/catalog photos:
   - Visible watermarks (e.g. Shutterstock, Getty), overly polished/studio-lit product shots,
     or visual styles consistent with stock libraries.

Respond ONLY with valid JSON matching this exact schema – no extra text:
{
  "is_green": <bool>,
  "is_round": <bool>,
  "is_ai_generated": <bool>,
  "is_stock_image": <bool>,
  "confidence": "<high|medium|low>",
  "flag_for_manual_review": <bool>,
  "reasoning": "<one or two concise sentences explaining the decision>"
}"""


def analyse_image_with_claude(
    client: anthropic.Anthropic,
    image_source: str,
) -> Optional[ImageAnalysis]:
    """
    Call Claude vision API and return a validated ImageAnalysis, or None on error.
    Uses prompt caching on the stable system prompt to cut costs across many calls.
    """
    try:
        b64_data, media_type = load_image_as_base64(image_source)
    except Exception as exc:
        log.error("Failed to load image %s: %s", image_source, exc)
        return None

    try:
        response = client.messages.parse(
            model="claude-opus-4-6",
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # cache stable system prompt
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Please validate this contest entry image against all four criteria "
                                "and return your JSON decision."
                            ),
                        },
                    ],
                }
            ],
            output_format=ImageAnalysis,
        )
        return response.parsed_output

    except anthropic.BadRequestError as exc:
        log.error("Claude rejected image %s: %s", image_source, exc)
        return None
    except Exception as exc:
        log.error("Claude API error for %s: %s", image_source, exc)
        return None


# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------

AUDIT_COLUMNS = [
    "timestamp", "entry_id", "phone", "image_url",
    "status", "rejection_reasons",
    "is_green", "is_round", "is_ai_generated", "is_stock_image",
    "confidence", "flag_for_manual_review", "reasoning",
]


class AuditLogger:
    def __init__(self, log_file: str = LOG_FILE):
        self.log_file = log_file
        self._ensure_header()

    def _ensure_header(self):
        if not Path(self.log_file).exists():
            with open(self.log_file, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=AUDIT_COLUMNS).writeheader()

    def log(self, entry: dict, status: str, reasons: List[str], analysis: Optional[ImageAnalysis]):
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "entry_id": entry.get("entry_id", ""),
            "phone": entry.get("phone", ""),
            "image_url": entry.get("image_url", ""),
            "status": status,
            "rejection_reasons": "; ".join(reasons) if reasons else "",
            "is_green": analysis.is_green if analysis else "",
            "is_round": analysis.is_round if analysis else "",
            "is_ai_generated": analysis.is_ai_generated if analysis else "",
            "is_stock_image": analysis.is_stock_image if analysis else "",
            "confidence": analysis.confidence if analysis else "",
            "flag_for_manual_review": analysis.flag_for_manual_review if analysis else "",
            "reasoning": analysis.reasoning if analysis else "",
        }
        with open(self.log_file, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=AUDIT_COLUMNS).writerow(row)
        log.info(
            "Entry %-20s  %-22s  reasons=%s",
            entry.get("entry_id", "?"),
            status.upper(),
            reasons or "none",
        )


# ---------------------------------------------------------------------------
# Processed-IDs tracker  (persisted between runs)
# ---------------------------------------------------------------------------

def load_processed_ids() -> Set[str]:
    p = Path(PROCESSED_IDS_FILE)
    if not p.exists():
        return set()
    return set(p.read_text(encoding="utf-8").splitlines())


def save_processed_id(entry_id: str):
    with open(PROCESSED_IDS_FILE, "a", encoding="utf-8") as f:
        f.write(entry_id + "\n")


# ---------------------------------------------------------------------------
# Data source  –  CUSTOMISE THIS FUNCTION
# ---------------------------------------------------------------------------

def fetch_pending_entries() -> List[dict]:
    """
    Return a list of dicts, each with at minimum:
        entry_id  : str  – unique identifier
        phone     : str  – contact phone number
        image_url : str  – URL or local path to the submitted image
        timestamp : str  – ISO 8601 submission time (optional but useful)

    DEFAULT IMPLEMENTATION reads from `entries_pending.csv`.
    Replace this body with your own API call / DB query as needed.

    Example API replacement:
        resp = requests.get("https://your-backend.com/api/entries?status=pending",
                            headers={"Authorization": f"Bearer {os.environ['API_TOKEN']}"})
        resp.raise_for_status()
        return resp.json()["entries"]
    """
    if not Path(PENDING_CSV).exists():
        log.warning("No pending entries file found at %s", PENDING_CSV)
        return []

    entries = []
    with open(PENDING_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(dict(row))
    log.info("Fetched %d pending entries from %s", len(entries), PENDING_CSV)
    return entries


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------

def validate_entry(
    entry: dict,
    client: anthropic.Anthropic,
    seen_image_hashes: Set[str],
    processed_ids: Set[str],
) -> Tuple[str, List[str], Optional[ImageAnalysis]]:
    """
    Returns (status, rejection_reasons, analysis).
    status is one of: "approved" | "rejected" | "flagged_for_manual_review"
    """
    entry_id = entry.get("entry_id", "")
    phone = entry.get("phone", "")
    image_url = entry.get("image_url", "")

    rejection_reasons: List[str] = []
    analysis: Optional[ImageAnalysis] = None

    # ------------------------------------------------------------------
    # 1. Duplicate check (by entry_id and by image hash)
    # ------------------------------------------------------------------
    if entry_id in processed_ids:
        rejection_reasons.append("Duplicate entry (already processed)")
        return "rejected", rejection_reasons, None

    img_hash = image_sha256(image_url)
    if img_hash and img_hash in seen_image_hashes:
        rejection_reasons.append("Duplicate image (identical photo submitted before)")
        return "rejected", rejection_reasons, None
    if img_hash:
        seen_image_hashes.add(img_hash)

    # ------------------------------------------------------------------
    # 2. Phone number validation
    # ------------------------------------------------------------------
    phone_valid, phone_reason = validate_phone(phone)
    if not phone_valid:
        rejection_reasons.append(f"Invalid phone number: {phone_reason}")
        # Do NOT return early – continue to image validation so the log is complete

    # ------------------------------------------------------------------
    # 3. Image validation via Claude
    # ------------------------------------------------------------------
    if image_url:
        analysis = analyse_image_with_claude(client, image_url)
    else:
        rejection_reasons.append("No image submitted")

    if analysis is None:
        if not rejection_reasons:
            rejection_reasons.append("Image could not be loaded or analysed")
        return "rejected", rejection_reasons, None

    # Apply image-based rejection rules
    if not analysis.is_green:
        rejection_reasons.append("Object is not green in colour")
    if not analysis.is_round:
        rejection_reasons.append("Object is not round in shape")
    if analysis.is_ai_generated:
        rejection_reasons.append("Image appears to be AI-generated")
    if analysis.is_stock_image:
        rejection_reasons.append("Image appears to be a stock photo")

    # ------------------------------------------------------------------
    # 4. Determine final status
    # ------------------------------------------------------------------
    if rejection_reasons:
        return "rejected", rejection_reasons, analysis

    if analysis.flag_for_manual_review:
        return "flagged_for_manual_review", ["Borderline case – flagged for human review"], analysis

    return "approved", [], analysis


# ---------------------------------------------------------------------------
# Validation cycle
# ---------------------------------------------------------------------------

def run_validation_cycle(
    client: anthropic.Anthropic,
    audit_logger: AuditLogger,
    seen_image_hashes: Set[str],
):
    log.info("=== Validation cycle started ===")
    processed_ids = load_processed_ids()
    entries = fetch_pending_entries()

    if not entries:
        log.info("No pending entries – nothing to do.")
        return

    approved = rejected = flagged = 0

    for entry in entries:
        entry_id = entry.get("entry_id", "")
        if not entry_id:
            log.warning("Entry missing entry_id, skipping: %s", entry)
            continue

        try:
            status, reasons, analysis = validate_entry(
                entry, client, seen_image_hashes, processed_ids
            )
        except Exception as exc:
            log.error("Unexpected error validating entry %s: %s", entry_id, exc)
            status = "rejected"
            reasons = [f"Internal error during validation: {exc}"]
            analysis = None

        audit_logger.log(entry, status, reasons, analysis)
        save_processed_id(entry_id)
        processed_ids.add(entry_id)

        if status == "approved":
            approved += 1
        elif status == "rejected":
            rejected += 1
        else:
            flagged += 1

    log.info(
        "=== Cycle complete: %d approved | %d rejected | %d flagged for review ===",
        approved, rejected, flagged,
    )


# ---------------------------------------------------------------------------
# Main loop with randomised 20-30 minute intervals
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set.\n"
            "Run:  export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)
    audit_logger = AuditLogger(LOG_FILE)

    # In-memory image hash set; pre-populate from existing log to survive restarts
    seen_image_hashes: Set[str] = set()

    log.info("Validator started.")
    log.info("Audit log  → %s", LOG_FILE)
    log.info("Pending entries source → %s", PENDING_CSV)
    log.info(
        "Check interval → %d–%d minutes (randomised)",
        MIN_INTERVAL_SECONDS // 60,
        MAX_INTERVAL_SECONDS // 60,
    )

    # Run immediately on startup
    run_validation_cycle(client, audit_logger, seen_image_hashes)

    # Then loop with random intervals
    while True:
        delay = random.randint(MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS)
        log.info("Next check in %.1f minutes.", delay / 60)
        time.sleep(delay)
        run_validation_cycle(client, audit_logger, seen_image_hashes)


if __name__ == "__main__":
    main()
