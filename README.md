# Green Automation

Bulk registration tool for greendotball.com and a contest entry validator. Generates unique Indian phone numbers, creates green-circle images, submits entries via browser automation, and validates incoming submissions using Claude's vision API.

---

## Project Structure

```
green-automation/
├── main.py              # Orchestrator — run this to submit entries
├── register.py          # Playwright bot that fills and submits the form
├── generate_numbers.py  # Generates unique Indian mobile numbers
├── generate_images.py   # Generates green-circle PNG images
├── database.py          # SQLite wrapper for storing results
├── validate_entries.py  # Entry validator (runs every 20–30 min)
├── config.py            # Shared config (TARGET_URL, DB_PATH, etc.)
├── inspect_form.py      # One-off utility to inspect the live form
├── entries_pending.csv  # Input feed for the validator
├── requirements.txt     # Python dependencies
└── automation.log       # Created at runtime — logs all run activity
```

---

## Prerequisites

- Python **3.8+** (the `python` command on your PATH)
- `pip` for installing packages
- An **Anthropic API key** (only required if running `validate_entries.py`)

---

## Setup

### 1. Clone / download the project

```bash
git clone <repo-url>
cd green-automation
```

### 2. (Recommended) Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

---

## Running the Bulk Registration Tool (`main.py`)

### Dry-run (recommended first step — nothing is submitted)

Generates phone numbers and images, prints the full plan, then cleans up:

```bash
python main.py --count 10 --dry-run
```

### Live run

Submits entries to the form. The images folder is automatically deleted after each run:

```bash
python main.py --count 100
```

### Resume a previous run

Skips phone numbers already recorded in the database, useful if a run was interrupted:

```bash
python main.py --count 100 --resume
```

### Show the browser window (useful for debugging)

```bash
python main.py --count 10 --no-headless
```

### All options

| Flag | Default | Description |
|---|---|---|
| `--count N` | `10` | Number of registrations to attempt |
| `--batch-size N` | `10` | Registrations processed per batch |
| `--dry-run` | off | Print plan and verify selectors without submitting |
| `--no-headless` | off | Show the browser window |
| `--resume` | off | Skip numbers already in the database |

### Output files

After a live run you will find:

| File | Contents |
|---|---|
| `registrations.db` | SQLite database with every attempt |
| `successful_numbers.csv` | Phone numbers that registered successfully |
| `failed_numbers.csv` | Phone numbers that failed, with error messages |
| `automation.log` | Timestamped log of every run (appended each time) |

---

## Running the Entry Validator (`validate_entries.py`)

The validator checks each pending submission against five rules: must be green, must be round, not AI-generated, not a stock image, and no duplicate entries. It runs in a loop with a randomised 20–30 minute interval.

### 1. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Add entries to validate

Edit `entries_pending.csv` — it must have these columns:

```
entry_id,phone,image_url,timestamp
entry_001,+919876543210,https://example.com/photo.jpg,2026-04-16T10:00:00
```

`image_url` can be a URL or a local file path.

### 3. Start the validator

```bash
python validate_entries.py
```

It runs immediately on start, then sleeps 20–30 minutes between cycles. Press `Ctrl+C` to stop.

### Output files

| File | Contents |
|---|---|
| `validation_log.csv` | Full audit trail — every entry, decision, and reason |
| `processed_ids.txt` | Entry IDs already processed (prevents re-validation on restart) |
| `validator.log` | Runtime log |

### Validation rules

| Rule | Result if violated |
|---|---|
| Duplicate entry (same ID or same image) | `rejected` |
| Object is not green | `rejected` |
| Object is not round | `rejected` |
| Image appears AI-generated | `rejected` |
| Image appears to be a stock photo | `rejected` |
| Invalid or fake phone number | `rejected` |
| Borderline / uncertain | `flagged_for_manual_review` |

---

## Utilities

### Inspect the live form

Opens a real browser window, prints all form fields and selectors, and saves a screenshot:

```bash
python inspect_form.py
```

---

## Troubleshooting

**`playwright install` fails or browser not found**
Run `playwright install --with-deps chromium` to also install OS-level dependencies.

**`ModuleNotFoundError` for `anthropic`, `phonenumbers`, etc.**
Make sure you activated your virtual environment and ran `pip install -r requirements.txt`.

**Registrations all fail with "Page returned HTTP 403"**
The site's CDN may be rate-limiting your IP. Reduce `--count`, add a longer delay in `config.py`, or try again later.

**`validate_entries.py` errors with "ANTHROPIC_API_KEY not set"**
Export the key before running: `export ANTHROPIC_API_KEY=sk-ant-...`
