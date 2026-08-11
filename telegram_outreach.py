#!/usr/bin/env python3
"""
telegram_outreach.py - Lead outreach via the Telegram Bot API.

Reads leads from ``leads.json`` and sends the outreach template through the
configured Telegram bot (``TELEGRAM_BOT_TOKEN`` in ``.env``), using
``sent_history.json`` to prevent duplicates.

PLATFORM LIMITATION (IMPORTANT)
-------------------------------
Telegram bots CANNOT message users by phone number. The Bot API offers no
phone-number -> chat_id resolution, and a bot may only send messages to
users who have already started a chat with the bot (pressed /start, which
yields their numeric chat_id). A lead is reachable only when ``leads.json``
provides one of:

    "telegram_chat_id": 123456789            # numeric chat id (user started the bot)
    "telegram_username": "some_username"     # @username (works for public
                                             # channels/groups; private users
                                             # still need to have started the bot)

Leads that only carry a phone number are reported as UNREACHABLE by this
script - no transmission is attempted for them.

Also note: sending unsolicited messages violates Telegram's Terms of Service
and can get the bot banned. Only message recipients who have opted in.

Usage
-----
    python3 telegram_outreach.py                 # dry-run (safe, default)
    python3 telegram_outreach.py --validate      # show leads + reachability
    python3 telegram_outreach.py --send          # transmit (token required)
    python3 telegram_outreach.py --send --limit 3
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

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a soft dependency
    load_dotenv = None

import httpx

PROJECT_DIR = Path(__file__).resolve().parent
LEADS_FILE = PROJECT_DIR / "leads.json"
SENT_HISTORY_FILE = PROJECT_DIR / "sent_history.json"
LOG_FILE = PROJECT_DIR / "logs" / "telegram_outreach.log"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")

DEFAULT_TEMPLATE = (
    "שלום {name}, אנו מציעים פתרון חכם לניהול שיחות שלא נענו. "
    "ניתן ליצור קשר דרך הבוט שלנו: https://infinityempire.github.io/vocalizebot"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tg_outreach")


def setup_logging() -> None:
    """Route logs to stdout and to logs/telegram_outreach.log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    # httpx logs full request URLs (which embed the bot token) at INFO -
    # suppress its logger so the token never appears in our logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_bot_token() -> str:
    """Load TELEGRAM_BOT_TOKEN from .env / environment."""
    if load_dotenv is not None:
        load_dotenv(PROJECT_DIR / ".env")
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


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
        if not name:
            logger.warning(f"lead[{i}]: missing 'name', skipping")
            continue
        valid.append(lead)
    return valid


def resolve_target(lead: dict):
    """Return (target, kind) for a lead.

    kind is one of: "chat_id", "username", "phone_only" (unreachable via bot).
    """
    chat_id = lead.get("telegram_chat_id")
    if chat_id is not None and str(chat_id).strip():
        return str(chat_id).strip(), "chat_id"

    username = str(lead.get("telegram_username", "")).strip().lstrip("@")
    if username and USERNAME_RE.match(username):
        return f"@{username}", "username"

    return None, "phone_only"


def load_sent_history() -> set:
    """Load identifiers already contacted (phones, chat ids, usernames)."""
    if not SENT_HISTORY_FILE.exists():
        return set()
    try:
        data = json.loads(SENT_HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    keys = set()
    if isinstance(data, list):
        for item in data:
            if not item:
                continue
            if isinstance(item, dict):
                for key in ("phone", "chat_id", "username"):
                    if item.get(key):
                        keys.add(str(item[key]).lstrip("@"))
            else:
                keys.add(str(item).lstrip("@"))
    elif isinstance(data, dict):
        keys.update(str(x).lstrip("@") for x in data.get("sent", []))
    return keys


def save_sent_history(entries: list) -> None:
    """Persist the sent history atomically (list of {phone, target, sent_at})."""
    SENT_HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(f"sent_history.json updated ({len(entries)} entries)")


def build_message(lead: dict, template: str) -> str:
    """Render the message template for a lead."""
    return template.format(name=lead.get("name", ""))


def send_via_telegram(token: str, target: str, message: str) -> bool:
    """Send a message through the Telegram Bot API. Returns True on success."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json={"chat_id": target, "text": message})
            data = resp.json()
        if data.get("ok"):
            return True
        desc = data.get("description", "unknown error")
        logger.error(f"Telegram API error for {target}: {desc}")
        return False
    except Exception as e:  # network/timeout/parse errors
        logger.error(f"Send failed for {target}: {e}")
        return False


def run(args) -> int:
    setup_logging()
    token = get_bot_token()
    leads = load_leads()
    sent = load_sent_history()
    template = os.getenv("OUTREACH_MESSAGE_TEMPLATE", DEFAULT_TEMPLATE)
    delay = float(os.getenv("OUTREACH_DELAY_SECONDS", "2"))

    if args.validate:
        reachable = 0
        print(f"leads.json: {len(leads)} lead(s)")
        for lead in leads:
            target, kind = resolve_target(lead)
            phone = lead.get("phone", "-")
            if kind == "phone_only":
                print(f"  - {lead.get('name')} | {phone} | UNREACHABLE (phone-only)")
            else:
                reachable += 1
                print(f"  - {lead.get('name')} | {phone} | reachable via {target} ({kind})")
        print(f"\nReachable via Telegram bot: {reachable}/{len(leads)}")
        return 0

    if not leads:
        logger.error("No valid leads found in leads.json — nothing to do.")
        return 1

    # Build pending list (not already in sent history)
    pending = []
    skipped_dupes = 0
    for lead in leads:
        target, kind = resolve_target(lead)
        phone = str(lead.get("phone", "")).strip()
        ids = {phone} | ({target.lstrip("@")} if target else set())
        if ids & sent:
            skipped_dupes += 1
            continue
        pending.append((lead, target, kind))
    logger.info(
        f"Dry-run: {args.dry_run} | leads={len(leads)} pending={len(pending)} "
        f"already_sent={skipped_dupes}"
    )

    if args.limit:
        pending = pending[: args.limit]

    unreachable = [(l, t, k) for l, t, k in pending if k == "phone_only"]
    sendable = [(l, t, k) for l, t, k in pending if k != "phone_only"]

    if args.dry_run:
        for lead, target, kind in sendable:
            message = build_message(lead, template)
            print(f"[DRY-RUN] would send to {target} ({lead.get('name')}): {message}")
            logger.info(f"[DRY-RUN] {target} ({lead.get('name')})")
        for lead, target, kind in unreachable:
            print(
                f"[DRY-RUN] {lead.get('name')} ({lead.get('phone')}): "
                f"UNREACHABLE — Telegram bots cannot message phone numbers; "
                f"add telegram_chat_id/telegram_username to this lead."
            )
        print(
            f"\nDry-run complete: {len(sendable)} sendable, {len(unreachable)} "
            f"unreachable (phone-only). Run with --send to transmit."
        )
        return 0

    # Real send mode
    if not token:
        logger.error(
            "Refusing to send: TELEGRAM_BOT_TOKEN is not set in .env. "
            "Telegram outreach cannot transmit without a bot token."
        )
        return 1

    if not sendable:
        logger.warning("No reachable (non-phone-only) leads to message.")
        return 0

    # Load current history (may have grown since start)
    try:
        history = (
            json.loads(SENT_HISTORY_FILE.read_text(encoding="utf-8"))
            if SENT_HISTORY_FILE.exists()
            else []
        )
        if not isinstance(history, list):
            history = []
    except json.JSONDecodeError:
        history = []

    sent_count = 0
    for lead, target, kind in sendable:
        message = build_message(lead, template)
        if send_via_telegram(token, target, message):
            entry = {"phone": lead.get("phone", ""), "sent_at": datetime.now(timezone.utc).isoformat()}
            if kind == "chat_id":
                entry["chat_id"] = target
            else:
                entry["username"] = target.lstrip("@")
            history.append(entry)
            save_sent_history(history)
            sent_count += 1
            time.sleep(delay)
        else:
            logger.warning(f"Skipped {target} after send failure.")

    logger.info(f"Done: {sent_count}/{len(sendable)} sent, {len(unreachable)} unreachable (phone-only).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VocalizeBot Telegram lead outreach")
    parser.add_argument("--send", action="store_true", help="Actually send (requires TELEGRAM_BOT_TOKEN)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only (default)")
    parser.add_argument("--limit", type=int, default=0, help="Cap number of leads processed")
    parser.add_argument("--validate", action="store_true", help="Show leads + reachability only")
    args = parser.parse_args()

    # Explicit --dry-run always wins over --send (safety)
    args.dry_run = args.dry_run or not args.send
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
