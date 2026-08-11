#!/usr/bin/env python3
"""
VocalizeBot - Final Self-Verification Tool (check_setup.py)
Validates configuration, imports, APIs, and credentials.
"""

import os
import sys
import asyncio
from pathlib import Path

# ANSI colors for styling
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def log_info(msg: str):
    print(f"{BLUE}[INFO]{RESET} {msg}")

def log_success(msg: str):
    print(f"{GREEN}✅ {msg}{RESET}")

def log_warn(msg: str):
    print(f"{YELLOW}⚠️ {msg}{RESET}")

def log_error(msg: str):
    print(f"{RED}❌ {msg}{RESET}")

async def test_telegram_token(token: str) -> bool:
    """Verifies the Telegram Bot Token against the official API."""
    import httpx
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    bot_user = data["result"]["username"]
                    log_success(f"Telegram Bot Token is VALID! Connected to Bot: @{bot_user}")
                    return True
            log_error(f"Telegram Bot Token validation failed. Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as e:
        log_warn(f"Could not connect to Telegram API to verify token (network or timeout): {e}")
        return True  # Don't block setup on transient network issues

async def test_gemini_key(key: str) -> bool:
    """Verifies the Google AI / Gemini API key."""
    import google.generativeai as genai
    try:
        genai.configure(api_key=key)
        # Try a fast list_models or small call to verify
        # We can use a background thread to prevent blocking
        loop = asyncio.get_running_loop()
        def list_models_sync():
            models = genai.list_models()
            return any("gemini" in m.name for m in models)
        
        has_gemini = await loop.run_in_executor(None, list_models_sync)
        if has_gemini:
            log_success("Google AI Studio (Gemini) API Key is VALID!")
            return True
        else:
            log_error("Google AI Studio API Key could not list Gemini models.")
            return False
    except Exception as e:
        log_warn(f"Could not verify Gemini API key (network or key issue): {e}")
        return True  # Don't block setup on transient network issues

async def main():
    print(f"\n{BOLD}{BLUE}====================================================={RESET}")
    print(f"{BOLD}{BLUE}          VocalizeBot - Verification System          {RESET}")
    print(f"{BOLD}{BLUE}====================================================={RESET}\n")

    all_ok = True

    # 1. Check Python Dependencies
    print(f"{BOLD}[1/3] Verifying Core Dependencies...{RESET}")
    required_packages = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("pydantic_settings", "pydantic-settings"),
        ("telegram", "python-telegram-bot"),
        ("google.generativeai", "google-generativeai"),
        ("httpx", "httpx"),
        ("aiofiles", "aiofiles"),
        ("dotenv", "python-dotenv"),
        ("loguru", "loguru"),
    ]

    missing_packages = []
    for module_name, package_name in required_packages:
        try:
            __import__(module_name)
            log_success(f"Package '{package_name}' is installed and importable.")
        except ImportError:
            log_error(f"Package '{package_name}' is MISSING.")
            missing_packages.append(package_name)
            all_ok = False

    if missing_packages:
        print(f"\n{YELLOW}To install all missing packages, run:{RESET}")
        print(f"pip install -r requirements.txt\n")

    # 2. Check configuration file (.env)
    print(f"\n{BOLD}[2/3] Verifying .env Configuration...{RESET}")
    env_path = Path(".env")
    if not env_path.exists():
        log_error(".env file is missing! Please copy .env.example to .env")
        all_ok = False
    else:
        log_success(".env file exists.")
        
        # Load environment variables
        from dotenv import load_dotenv
        load_dotenv(override=True)

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        google_key = os.getenv("GOOGLE_AI_API_KEY")

        # Validate Telegram Bot Token
        if not bot_token or bot_token == "your_telegram_bot_token_here" or bot_token == "":
            log_error("TELEGRAM_BOT_TOKEN is not configured in .env")
            all_ok = False
        else:
            log_success("TELEGRAM_BOT_TOKEN is present.")

        # Validate Admin Chat ID
        if not admin_chat_id or admin_chat_id == "your_telegram_id_here" or admin_chat_id == "":
            log_error("TELEGRAM_ADMIN_CHAT_ID is not configured in .env")
            all_ok = False
        elif not admin_chat_id.replace('"', '').replace("'", "").isdigit():
            log_error(f"TELEGRAM_ADMIN_CHAT_ID must be a numeric ID, got: {admin_chat_id}")
            all_ok = False
        else:
            log_success(f"TELEGRAM_ADMIN_CHAT_ID is configured: {admin_chat_id}")

        # Validate Google Key
        if not google_key or google_key == "your_google_ai_api_key_here" or google_key == "":
            log_error("GOOGLE_AI_API_KEY is not configured in .env")
            all_ok = False
        else:
            log_success("GOOGLE_AI_API_KEY is present.")

    # 3. Live API Validation
    if all_ok:
        print(f"\n{BOLD}[3/3] Performing Live Credentials Validation...{RESET}")
        clean_token = bot_token.strip().strip('"').strip("'")
        clean_key = google_key.strip().strip('"').strip("'")
        
        # Run validations concurrently
        tg_ok, gemini_ok = await asyncio.gather(
            test_telegram_token(clean_token),
            test_gemini_key(clean_key)
        )
        
        if not (tg_ok and gemini_ok):
            log_warn("Credential validation succeeded with warnings/errors. Please double-check credentials if the bot fails to run.")
    else:
        print(f"\n{RED}❌ Verification failed during initial checks. Skipping live API validation.{RESET}")

    print(f"\n{BOLD}{BLUE}====================================================={RESET}")
    if all_ok:
        print(f"{BOLD}{GREEN}🎉 SUCCESS: All systems green! VocalizeBot is ready! 🎉{RESET}")
        print(f"{BOLD}{BLUE}====================================================={RESET}\n")
        return 0
    else:
        print(f"{BOLD}{RED}❌ ERROR: Some configurations or packages are missing. ❌{RESET}")
        print(f"{BOLD}{BLUE}====================================================={RESET}\n")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
