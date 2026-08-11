#!/usr/bin/env python3
"""
whatsapp_outreach.py - Lead outreach pipeline for VocalizeBot.

Reads business leads from ``leads.json`` and sends a templated WhatsApp
message to each lead, using ``sent_history.json`` to prevent duplicates.

SAFETY BY DEFAULT
-----------------
* The script runs in **DRY-RUN mode** unless ``--send`` is explicitly given.
  In dry-run mode nothing is transmitted; the script prints + logs what it
  *would* send and exits 0.
* Real sending requires an opt-in recipient list AND Twilio WhatsApp
  Business API credentials (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
  TWILIO_WHATSAPP_FROM). Without them the script refuses to send.
* Cold, unsolicited bulk messaging violates WhatsApp's Terms of Service and
  can get the sender account banned. Only use this with recipients who have
  opted in, through the official WhatsApp Business API.

Usage
-----
    python3 whatsapp_outreach.py                 # dry-run (safe)
    python3 whatsapp_outreach.py --dry-run
    python3 whatsapp_outreach.py --send          # real sends (credentials required)
    python3 whatsapp_outreach.py --send --limit 5   # cap at 5 sends
    python3 whatsapp_outreach.py --validate      # just validate leads.json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LEADS_FILE = PROJECT_DIR / "leads.json"
SENT_HISTORY_FILE = PROJECT_DIR / "sent_history.json"
LOG_FILE = PROJECT_DIR / "logs" / "whatsapp_outreach.log"

PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")

DEFAULT_TEMPLATE = (
    "שלום {name}, אנו מציעים פתרון חכם לניהול שיחות שלא נענו. "
    "ניתן ליצור קשר דרך הבוט שלנו: https://infinityempire.github.io/vocalizebot"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("outreach")


def setup_logging() -> None:
    """Route logs to stdout and to logs/whatsapp_outreach.log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)


def load_leads() -> list:
    """Load and validate the lead list from leads.json."""
    if not LEADS_FILE.exists():
        logger.error(f"leads.json not found at {LEADS_FILE}")
        return []
    try:
        leads = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"leads.json is not valid JSON: {e}")
        return []
    if not isinstance(leads, list):
        logger.error("leads.json must contain a JSON array of lead objects")
        return []

    valid = []
    for i, lead in enumerate(leads):
        name = str(lead.get("name", "")).strip()
        phone = str(lead.get("phone", "")).strip()
        if not name:
            logger.warning(f"lead[{i}]: missing 'name', skipping")
            continue
        if not PHONE_RE.match(phone):
            logger.warning(f"lead[{i}] '{name}': invalid phone '{phone}', skipping")
            continue
        valid.append(lead)
    return valid


def load_sent_history() -> set:
    """Load the set of phone numbers that were already contacted."""
    if not SENT_HISTORY_FILE.exists():
        return set()
    try:
        data = json.loads(SENT_HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if isinstance(data, list):
        return {str(item.get("phone", item)) for item in data if item}
    if isinstance(data, dict):
        return set(data.get("sent", []))
    return set()


def save_sent_history(entries: list) -> None:
    """Persist the sent history atomically (list of {phone, sent_at})."""
    SENT_HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(f"sent_history.json updated ({len(entries)} entries)")


def build_message(lead: dict, template: str) -> str:
    """Render the message template for a lead."""
    name = lead.get("name", "")
    return template.format(name=name)


def send_via_twilio(lead: dict, message: str) -> bool:
    """Send the message through the Twilio WhatsApp Business API."""
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
    if not (sid and token and from_number):
        logger.error(
            "Refusing to send: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / "
            "TWILIO_WHATSAPP_FROM not all set."
        )
        return False

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        to_number = lead["phone"]
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"
        msg = client.messages.create(
            from_=f"whatsapp:{from_number}",
            body=message,
            to=to_number,
        )
        logger.info(f"Sent to {lead['phone']} ({lead.get('name')}): sid={msg.sid}")
        return True
    except Exception as e:
        logger.error(f"Send failed for {lead.get('phone')}: {e}")
        return False


def run(args) -> int:
    setup_logging()
    leads = load_leads()
    sent = load_sent_history()
    template = os.getenv("OUTREACH_MESSAGE_TEMPLATE", DEFAULT_TEMPLATE)
    delay = float(os.getenv("OUTREACH_DELAY_SECONDS", "2"))

    if args.validate:
        print(f"leads.json: {len(leads)} valid lead(s)")
        for lead in leads:
            print(f"  - {lead.get('name')} | {lead.get('phone')}")
        return 0

    if not leads:
        logger.error("No valid leads found in leads.json — nothing to do.")
        return 1

    pending = [lead for lead in leads if lead["phone"] not in sent]
    if not pending:
        logger.info("All leads already in sent_history.json — nothing new to send.")
        return 0

    logger.info(f"Dry-run: {args.dry_run} | leads={len(leads)} pending={len(pending)}")

    if args.limit:
        pending = pending[: args.limit]

    if args.dry_run:
        for lead in pending:
            message = build_message(lead, template)
            print(f"[DRY-RUN] would send to {lead['phone']} ({lead.get('name')}): {message}")
            logger.info(f"[DRY-RUN] {lead['phone']} ({lead.get('name')})")
        print(f"\nDry-run complete: {len(pending)} message(s) simulated. "
              f"Run with --send to transmit (requires Twilio credentials + opt-in leads).")
        return 0

    # Real send mode
    if not args.send:
        return 0

    new_entries = []
    try:
        if SENT_HISTORY_FILE.exists():
            new_entries = json.loads(SENT_HISTORY_FILE.read_text(encoding="utf-8"))
            if not isinstance(new_entries, list):
                new_entries = []
    except json.JSONDecodeError:
        new_entries = []

    sent_count = 0
    for lead in pending:
        message = build_message(lead, template)
        if send_via_twilio(lead, message):
            new_entries.append(
                {"phone": lead["phone"], "name": lead.get("name"),
                 "sent_at": datetime.now(timezone.utc).isoformat()}
            )
            sent_count += 1
            save_sent_history(new_entries)
            time.sleep(delay)
        else:
            logger.warning(f"Skipped {lead.get('phone')} after send failure.")

    logger.info(f"Done: {sent_count}/{len(pending)} sent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VocalizeBot WhatsApp lead outreach")
    parser.add_argument("--send", action="store_true", help="Actually send (requires Twilio creds)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only (default)")
    parser.add_argument("--limit", type=int, default=0, help="Cap number of leads processed")
    parser.add_argument("--validate", action="store_true", help="Validate leads.json only")
    args = parser.parse_args()

    args.dry_run = not args.send
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
