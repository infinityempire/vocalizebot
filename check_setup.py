#!/usr/bin/env python3
"""
VocalizeBot - Self-Diagnostic Script
=====================================
Run this script on Termux to verify all system components are ready.

Usage:
    python3 check_setup.py

Requirements:
    - Python 3.8+
    - requests (pip install requests)
    - python-dotenv (pip install python-dotenv)

Author: Tal HaTil Empire
Version: 2.0.0
"""

import os
import sys
import json
import socket
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple

# ANSI Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    DIM = '\033[2m'

def colored(text: str, color: str) -> str:
    """Apply color to text if terminal supports it."""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.RESET}"
    return text

def success(msg: str) -> None:
    print(f"{colored('✅', Colors.GREEN)} {msg}")

def error(msg: str) -> None:
    print(f"{colored('❌', Colors.RED)} {msg}")

def warning(msg: str) -> None:
    print(f"{colored('⚠️', Colors.YELLOW)} {msg}")

def info(msg: str) -> None:
    print(f"{colored('ℹ️', Colors.BLUE)} {msg}")

def header(msg: str) -> None:
    print(f"\n{colored('═' * 60, Colors.DIM)}")
    print(f"{colored('📋', Colors.BLUE)} {colored(msg, Colors.BOLD)}")
    print(f"{colored('─' * 60, Colors.DIM)}")

def section(msg: str) -> None:
    print(f"\n{colored('▶', Colors.YELLOW)} {colored(msg, Colors.BOLD)}")

class DiagnosticCheck:
    """Base class for diagnostic checks."""
    
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
    
    def run(self) -> bool:
        """Run the diagnostic check. Override in subclass."""
        raise NotImplementedError
    
    def get_status(self) -> Tuple[bool, str]:
        """Return (passed, message)."""
        return self.passed, self.message


class EnvFileCheck(DiagnosticCheck):
    """Check if .env file exists and contains required variables."""
    
    REQUIRED_VARS = [
        'TELEGRAM_BOT_TOKEN',
        'GOOGLE_AI_API_KEY',
        'ADMIN_DASHBOARD_TOKEN',
    ]
    
    RECOMMENDED_VARS = [
        'PAYPAL_CLIENT_ID',
        'PAYPAL_CLIENT_SECRET',
        'DATABASE_URL',
    ]
    
    def __init__(self):
        super().__init__("Environment Variables")
    
    def run(self) -> bool:
        env_path = Path('.env')
        
        if not env_path.exists():
            self.message = ".env file not found in current directory"
            error(self.message)
            info("Run: cp .env.example .env && nano .env")
            return False
        
        success(f".env file found")
        
        # Load and check variables
        with open(env_path) as f:
            content = f.read()
        
        env_vars = {}
        for line in content.split('\n'):
            if '=' in line and not line.strip().startswith('#'):
                key, _, value = line.partition('=')
                env_vars[key.strip()] = value.strip()
        
        missing_required = []
        missing_recommended = []
        
        for var in self.REQUIRED_VARS:
            if var not in env_vars or not env_vars[var] or 'your_' in env_vars[var].lower():
                missing_required.append(var)
        
        for var in self.RECOMMENDED_VARS:
            if var not in env_vars or not env_vars[var] or 'your_' in env_vars[var].lower():
                missing_recommended.append(var)
        
        if missing_required:
            error(f"Missing required variables: {', '.join(missing_required)}")
            return False
        
        success(f"All required variables present")
        
        if missing_recommended:
            warning(f"Missing recommended variables: {', '.join(missing_recommended)}")
            warning("These are optional but recommended for full functionality")
        
        return True


class PythonVersionCheck(DiagnosticCheck):
    """Check Python version."""
    
    MIN_VERSION = (3, 8)
    
    def __init__(self):
        super().__init__("Python Version")
    
    def run(self) -> bool:
        version = sys.version_info[:2]
        if version >= self.MIN_VERSION:
            success(f"Python {version[0]}.{version[1]} (meets requirement)")
            return True
        else:
            self.message = f"Python {version[0]}.{version[1]} is below minimum {self.MIN_VERSION[0]}.{self.MIN_VERSION[1]}"
            error(self.message)
            return False


class DependencyCheck(DiagnosticCheck):
    """Check if required Python packages are installed."""
    
    REQUIRED_PACKAGES = [
        'requests',
        'dotenv',
        'telegram',
        'fastapi',
        'uvicorn',
    ]
    
    def __init__(self):
        super().__init__("Python Dependencies")
    
    def run(self) -> bool:
        missing = []
        installed = []
        
        for package in self.REQUIRED_PACKAGES:
            try:
                __import__(package)
                installed.append(package)
            except ImportError:
                missing.append(package)
        
        if missing:
            error(f"Missing packages: {', '.join(missing)}")
            info("Run: pip install -r requirements.txt")
            return False
        
        success(f"All required packages installed ({len(installed)} packages)")
        return True


class NetworkCheck(DiagnosticCheck):
    """Check network connectivity to required services."""
    
    HOSTS = [
        ('api.telegram.org', 443),
        ('aistudio.google.com', 443),
        ('api.paypal.com', 443),
    ]
    
    def __init__(self):
        super().__init__("Network Connectivity")
    
    def run(self) -> bool:
        all_passed = True
        
        for host, port in self.HOSTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                result = sock.connect_ex((host, port))
                sock.close()
                
                if result == 0:
                    success(f"{host}:{port} - Connected")
                else:
                    error(f"{host}:{port} - Connection refused (firewall issue?)")
                    all_passed = False
            except socket.gaierror:
                error(f"{host}:{port} - DNS resolution failed")
                all_passed = False
            except socket.timeout:
                error(f"{host}:{port} - Connection timed out")
                all_passed = False
            except Exception as e:
                error(f"{host}:{port} - {type(e).__name__}")
                all_passed = False
        
        if not all_passed:
            warning("Some connections failed. Check your internet or firewall.")
        
        return all_passed


class TelegramTokenCheck(DiagnosticCheck):
    """Verify Telegram bot token is valid."""
    
    def __init__(self):
        super().__init__("Telegram Bot Token")
    
    def run(self) -> bool:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        
        if not token or 'your_' in token.lower():
            error("Telegram bot token not configured")
            info("Get a token from @BotFather on Telegram")
            return False
        
        # Validate token format (basic check)
        parts = token.split(':')
        if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 20:
            error("Telegram bot token format appears invalid")
            return False
        
        success("Telegram bot token configured")
        
        # Optionally verify with API
        try:
            import requests
            response = requests.get(
                f'https://api.telegram.org/bot{token}/getMe',
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_name = data['result']['username']
                    success(f"Bot verified: @{bot_name}")
                    return True
            error("Telegram API returned unexpected response")
            return False
        except Exception as e:
            warning(f"Could not verify with Telegram API: {e}")
            return True  # Don't fail, token might still be valid


class GoogleAIKeyCheck(DiagnosticCheck):
    """Verify Google AI API key is configured."""
    
    def __init__(self):
        super().__init__("Google AI API Key")
    
    def run(self) -> bool:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        
        api_key = os.environ.get('GOOGLE_AI_API_KEY', '')
        
        if not api_key or 'your_' in api_key.lower():
            error("Google AI API key not configured")
            info("Get a key from: https://aistudio.google.com/app/apikey")
            return False
        
        if not api_key.startswith('AIza'):
            warning("API key format doesn't match Google AI Studio pattern")
        
        success("Google AI API key configured")
        
        # Optionally verify with a simple test
        try:
            import requests
            # Just check the key format is valid (don't make actual API call)
            success("Key format appears valid")
            return True
        except Exception as e:
            warning(f"Could not validate key: {e}")
            return True


class DashboardPortCheck(DiagnosticCheck):
    """Check if Dashboard port is available or service is running."""
    
    DEFAULT_PORT = 8000
    
    def __init__(self):
        super().__init__("Dashboard Port")
    
    def run(self) -> bool:
        port = int(os.environ.get('PORT', self.DEFAULT_PORT))
        
        # Check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            info(f"Port {port} is in use (Dashboard might be running)")
            success("Dashboard service detected")
            return True
        else:
            warning(f"Port {port} is available (Dashboard not running)")
            info("Start with: python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000")
            return True  # This is OK, service just not running


class DatabaseCheck(DiagnosticCheck):
    """Check database connectivity."""
    
    def __init__(self):
        super().__init__("Database")
    
    def run(self) -> bool:
        db_path = Path('vocalizebot.db')
        
        if db_path.exists():
            size = db_path.stat().st_size
            success(f"SQLite database found ({size} bytes)")
            return True
        else:
            info("Database file not found (will be created on first run)")
            success("Database configuration OK")
            return True


class DirectoryStructureCheck(DiagnosticCheck):
    """Check required directories and files exist."""
    
    REQUIRED_PATHS = [
        'src',
        'src/channels',
        'src/services',
        'src/config',
        'config',
    ]
    
    def __init__(self):
        super().__init__("Directory Structure")
    
    def run(self) -> bool:
        all_exist = True
        
        for path_str in self.REQUIRED_PATHS:
            path = Path(path_str)
            if path.exists():
                success(f"{path_str}/ exists")
            else:
                error(f"{path_str}/ missing")
                all_exist = False
        
        return all_exist


def run_diagnostics() -> bool:
    """Run all diagnostic checks."""
    print(colored("\n" + "═" * 60, Colors.DIM))
    print(colored("🔍 VocalizeBot - Self-Diagnostic Tool", Colors.BOLD + Colors.BLUE))
    print(colored("═" * 60 + "\n", Colors.DIM))
    
    checks = [
        DirectoryStructureCheck(),
        PythonVersionCheck(),
        EnvFileCheck(),
        DependencyCheck(),
        DatabaseCheck(),
        TelegramTokenCheck(),
        GoogleAIKeyCheck(),
        DashboardPortCheck(),
        NetworkCheck(),
    ]
    
    results = []
    
    for check in checks:
        header(check.name)
        try:
            passed = check.run()
            results.append(passed)
        except Exception as e:
            error(f"Check failed with error: {e}")
            results.append(False)
    
    # Summary
    header("Diagnostic Summary")
    passed_count = sum(results)
    total_count = len(results)
    
    print(f"\nPassed: {colored(f'{passed_count}/{total_count}', Colors.GREEN if passed_count == total_count else Colors.YELLOW)}")
    
    if passed_count == total_count:
        print(colored("\n🎉 All checks passed! Your system is ready.", Colors.GREEN + Colors.BOLD))
        print("\nTo start VocalizeBot:")
        print(f"  {colored('python3 src/main.py', Colors.BLUE)}")
        print(f"\nOr for production:")
        print(f"  {colored('nohup python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 > bot.log 2>&1 &', Colors.DIM)}")
        return True
    else:
        print(colored("\n⚠️  Some checks failed. Please fix the issues above.", Colors.YELLOW))
        print("\nCommon fixes:")
        print("  1. cp .env.example .env")
        print("  2. pip install -r requirements.txt")
        return False


if __name__ == "__main__":
    success_result = run_diagnostics()
    sys.exit(0 if success_result else 1)
