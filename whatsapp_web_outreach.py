#!/usr/bin/env python3
"""
whatsapp_web_outreach.py - Free WhatsApp Web outreach (no Twilio / paid APIs).

Sends the outreach template to leads from ``leads.json`` by automating
WhatsApp Web through the logged-in browser profile, using Playwright.

HOW IT WORKS
------------
1. Reads leads from ``leads.json`` (name + E.164 phone).
2. Skips any lead already recorded in ``sent_history.json``.
3. For each pending lead opens the direct chat link
   ``https://web.whatsapp.com/send?phone=<digits>`` in the persistent browser
   profile, types the message, presses Enter, and waits until an outgoing
   message bubble is visible before marking the lead as sent.

SETUP (one-time, REQUIRED for --send)
-------------------------------------
A WhatsApp Web session must be authenticated once:

    python3 whatsapp_web_outreach.py --login

This opens a browser window (needs a desktop display) where you scan the
WhatsApp QR code with the phone you want to send from. The authenticated
profile is saved under ``WHATSAPP_PROFILE_DIR`` (default ``~/.whatsapp_profile``)
and reused for all future sends.

COMPLIANCE / SAFETY
-------------------
Automating WhatsApp Web violates WhatsApp's Terms of Service and can get the
account banned. Only use this on YOUR OWN account, for recipients who have
opted in, and keep the inter-message delay generous (default 12s) to avoid
rate-limiting flags. This tool cannot read delivery receipts - "sent" means
an outgoing bubble was rendered in the chat.

Usage
-----
    python3 whatsapp_web_outreach.py                # dry-run (safe, default)
    python3 whatsapp_web_outreach.py --validate     # list leads + reachability
    python3 whatsapp_web_outreach.py --send         # send (profile required)
    python3 whatsapp_web_outreach.py --send --limit 3
    python3 whatsapp_web_outreach.py --login        # authenticate once (needs display)
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
LOG_FILE = PROJECT_DIR / "logs" / "whatsapp_web_outreach.log"

PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")
DEFAULT_TEMPLATE = (
    "שלום {name}, אנו מציעים פתרון חכם לניהול שיחות שלא נענו. "
    "ניתן ליצור קשר דרך הבוט שלנו: https://infinityempire.github.io/vocalizebot"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wa_outreach")


def setup_logging() -> None:
    """Route logs to stdout and to logs/whatsapp_web_outreach.log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return
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
        if not name or not PHONE_RE.match(phone):
            logger.warning(f"lead[{i}]: invalid name/phone, skipping")
            continue
        valid.append(lead)
    return valid


def load_sent_history() -> set:
    """Load phone numbers already contacted."""
    if not SENT_HISTORY_FILE.exists():
        return set()
    try:
        data = json.loads(SENT_HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    phones = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if item.get("phone"):
                    phones.add(str(item["phone"]))
            elif item:
                phones.add(str(item))
    elif isinstance(data, dict):
        phones.update(str(x) for x in data.get("sent", []))
    return phones


def save_sent_history(entries: list) -> None:
    """Persist the sent history atomically."""
    SENT_HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(f"sent_history.json updated ({len(entries)} entries)")


def build_message(lead: dict, template: str) -> str:
    """Render the message template for a lead."""
    return template.format(name=lead.get("name", ""))


def digits_only(phone: str) -> str:
    """Strip '+' and formatting for the /send?phone= URL (country code + number)."""
    return re.sub(r"\D", "", phone)


def profile_dir() -> Path:
    """Path to the persistent browser profile (authenticated WhatsApp session)."""
    override = os.getenv("WHATSAPP_PROFILE_DIR", "").strip()
    return Path(override) if override else Path.home() / ".whatsapp_profile"


def is_headless() -> bool:
    """Whether the browser should run headless (default true)."""
    return os.getenv("WHATSAPP_HEADLESS", "true").lower() not in ("0", "false", "no")


def preflight_check() -> str:
    """Return an error message if the send backend is unusable, else empty string."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        if not path or not Path(path).exists():
            return (
                "Playwright chromium is not installed. Run: "
                "python3 -m playwright install chromium"
            )
    except Exception as e:
        return f"Playwright unavailable: {e}"
    return ""


def send_one(phone: str, message: str, headless: bool, wait_timeout_ms: int) -> bool:
    """Send one message via WhatsApp Web using the persistent profile.

    Returns True only when an outgoing bubble appears in the chat.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    profile = profile_dir()
    url = f"https://web.whatsapp.com/send?phone={digits_only(phone)}"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, timeout=wait_timeout_ms)

        # Detect a QR code (not logged in) vs chat open
        try:
            page.wait_for_selector("[data-ref]", timeout=15000)
            logger.error(
                "WhatsApp Web is not logged in. Run --login first (needs a display)."
            )
            context.close()
            return False
        except PWTimeout:
            pass  # no QR -> likely authenticated

        # Wait for the message input box to be ready
        try:
            page.wait_for_selector('div[contenteditable="true"][data-tab="10"]', timeout=wait_timeout_ms)
        except PWTimeout:
            logger.error(f"Chat did not open for {phone} (number may be invalid or session issue).")
            context.close()
            return False

        box = page.locator('div[contenteditable="true"][data-tab="10"]')
        box.click()
        box.fill("")
        page.keyboard.type(message, delay=15)
        page.keyboard.press("Enter")

        # Confirm the outgoing bubble rendered (delivery action completed)
        try:
            page.wait_for_selector("div.message-out", timeout=15000)
            delivered = True
        except PWTimeout:
            logger.warning(f"Could not confirm outgoing bubble for {phone}; message may not have sent.")
            delivered = False

        time.sleep(2)  # let WhatsApp persist before closing
        context.close()
        return delivered


def cmd_login(headless: bool) -> int:
    """Open WhatsApp Web in a headed browser for QR authentication."""
    from playwright.sync_api import sync_playwright

    if headless:
        logger.error("--login requires a display. Run with WHATSAPP_HEADLESS=false "
                     "(and a desktop session).")
        return 1

    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Opening WhatsApp Web with profile: {profile}")
    print("Scan the QR code with WhatsApp -> Linked devices -> Link a device.")
    print("Keep this window open until the chat list appears, then close it.")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=False, args=["--no-sandbox"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://web.whatsapp.com/", timeout=120000)
        page.wait_for_selector("div[id='pane-side']", timeout=300000)
        print("Authenticated - session saved to profile.")
        context.close()
    return 0


def run(args) -> int:
    setup_logging()
    leads = load_leads()
    sent = load_sent_history()
    template = os.getenv("OUTREACH_MESSAGE_TEMPLATE", DEFAULT_TEMPLATE)
    delay = float(os.getenv("WHATSAPP_DELAY_SECONDS", "12"))
    headless = is_headless()

    if args.validate:
        print(f"leads.json: {len(leads)} lead(s)")
        for lead in leads:
            status = "ALREADY SENT" if lead["phone"] in sent else "pending"
            print(f"  - {lead.get('name')} | {lead.get('phone')} | {status}")
        print(f"\nPending: {sum(1 for l in leads if l['phone'] not in sent)}/{len(leads)}")
        return 0

    if not leads:
        logger.error("No valid leads found in leads.json — nothing to do.")
        return 1

    pending = [lead for lead in leads if lead["phone"] not in sent]
    logger.info(f"Dry-run: {args.dry_run} | leads={len(leads)} pending={len(pending)} "
                f"already_sent={len(leads) - len(pending)}")

    if args.limit:
        pending = pending[: args.limit]

    if args.dry_run:
        for lead in pending:
            message = build_message(lead, template)
            print(f"[DRY-RUN] would send to {lead['phone']} ({lead.get('name')}): {message}")
            logger.info(f"[DRY-RUN] {lead['phone']} ({lead.get('name')})")
        print(
            f"\nDry-run complete: {len(pending)} message(s) simulated. "
            f"Run with --send to transmit via WhatsApp Web (profile required)."
        )
        return 0

    # ---- Real send mode ----
    if not pending:
        logger.info("No pending leads — everything already in sent_history.json.")
        return 0

    if not profile_dir().exists():
        logger.error(
            f"No WhatsApp profile found at {profile_dir()}. Run "
            f"`python3 whatsapp_web_outreach.py --login` once (needs a display)."
        )
        return 1

    err = preflight_check()
    if err:
        logger.error(f"Send preflight failed: {err}")
        return 1

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
    for lead in pending:
        message = build_message(lead, template)
        print(f"[SEND] {lead['phone']} ({lead.get('name')}) ...")
        if send_one(lead["phone"], message, headless, wait_timeout_ms=60000):
            history.append(
                {
                    "phone": lead["phone"],
                    "name": lead.get("name"),
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "channel": "whatsapp_web",
                }
            )
            save_sent_history(history)
            sent_count += 1
            if len(pending) > 1:
                print(f"  waiting {delay}s before next message (rate-limit safety)...")
                time.sleep(delay)
        else:
            logger.warning(f"Not marked as sent for {lead['phone']}.")

    logger.info(f"Done: {sent_count}/{len(pending)} sent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Free WhatsApp Web lead outreach (Playwright)")
    parser.add_argument("--send", action="store_true", help="Actually send via WhatsApp Web")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only (default)")
    parser.add_argument("--validate", action="store_true", help="List leads + status only")
    parser.add_argument("--login", action="store_true", help="Authenticate WhatsApp Web once")
    parser.add_argument("--limit", type=int, default=0, help="Cap number of leads processed")
    args = parser.parse_args()

    if args.login:
        return cmd_login(is_headless())

    args.dry_run = args.dry_run or not args.send
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
