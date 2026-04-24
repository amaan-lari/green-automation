# Project Commands & Usage Instructions

## `main.py` — Bulk Registration Orchestrator

```bash
python main.py [flags]
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--count N` | `10` | Number of registrations to attempt |
| `--batch-size N` | `10` | How many registrations to run per batch |
| `--dry-run` | off | Print the plan + test bot on 1 entry — nothing gets submitted |
| `--no-headless` | off | Show the browser window (useful for debugging) |
| `--resume` | off | Skip phone numbers already used 10+ times in the DB |

### Example — Dry Run

Use this to preview the plan and watch the bot hit a new URL with the browser visible:

```bash
python main.py --count 5 --dry-run --no-headless
```

---

## `validate_entries.py` — Entry Validator

```bash
python validate_entries.py
```

No flags required. This script:

- Reads entries from `entries_pending.csv`
- Validates each entry via Claude vision (checks: green, round, not AI/stock image)
- Logs results to `validation_log.csv`
- Loops automatically every 20–30 minutes
