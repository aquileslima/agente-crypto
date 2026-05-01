#!/usr/bin/env python3
"""
Pre-deployment health check script.
Verifies all dependencies and configurations before deployment.
Run: python pre_deployment_check.py
"""
import os
import sys
from pathlib import Path

def check(condition, message, critical=False):
    """Print check result."""
    status = "✓" if condition else "✗"
    level = "ERROR" if not condition and critical else "WARNING"
    print(f"{status} {message}")
    return condition

def main():
    print("\n" + "="*60)
    print("Pre-Deployment Health Check")
    print("="*60 + "\n")

    errors = []
    warnings = []

    # ========================================================================
    # 1. File Structure
    # ========================================================================
    print("📁 File Structure")
    print("-" * 60)

    required_files = [
        "docker-compose.yml",
        "Dockerfile",
        ".env.example",
        "app.py",
        "bot.py",
        "config.py",
        "websocket_monitor.py",
        "websocket_direct.py",
        "requirements.txt",
    ]

    for file in required_files:
        exists = Path(file).exists()
        if not check(exists, f"  {file}", critical=True):
            errors.append(f"Missing required file: {file}")

    # ========================================================================
    # 2. Python Packages
    # ========================================================================
    print("\n📦 Python Packages")
    print("-" * 60)

    required_packages = [
        ("websockets", "WebSocket support"),
        ("requests", "HTTP requests"),
        ("dotenv", "Environment variables"),
        ("flask", "Web framework"),
        ("ccxt", "Exchange API"),
        ("pandas", "Data analysis"),
        ("anthropic", "Claude API"),
    ]

    for package, description in required_packages:
        try:
            __import__(package)
            check(True, f"  {package:15} ({description})")
        except ImportError:
            warning = f"Missing optional package: {package} ({description})"
            check(False, f"  {package:15} ({description})")
            warnings.append(warning)

    # ========================================================================
    # 3. Environment Variables
    # ========================================================================
    print("\n🔑 Environment Variables")
    print("-" * 60)

    required_env = [
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "ANTHROPIC_API_KEY",
    ]

    optional_env = [
        "BINANCE_TESTNET",
        "TRADING_MODE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "LOG_LEVEL",
    ]

    for var in required_env:
        exists = var in os.environ
        if not check(exists, f"  {var}", critical=True):
            errors.append(f"Missing required env var: {var}")

    for var in optional_env:
        exists = var in os.environ
        if not exists:
            warnings.append(f"Optional env var not set: {var}")
        check(exists, f"  {var} (optional)")

    # ========================================================================
    # 4. API Connectivity
    # ========================================================================
    print("\n🌐 API Connectivity")
    print("-" * 60)

    # Binance connectivity
    try:
        import requests
        response = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
        check(response.status_code == 200, "  Binance REST API reachable")
    except Exception as e:
        warnings.append(f"Binance API unreachable: {e}")
        check(False, f"  Binance REST API reachable")

    # Anthropic connectivity
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            from anthropic import Anthropic
            client = Anthropic()
            check(True, "  Anthropic SDK importable")
        else:
            check(False, "  Anthropic SDK importable")
    except Exception as e:
        warnings.append(f"Anthropic SDK issue: {e}")
        check(False, f"  Anthropic SDK importable")

    # ========================================================================
    # 5. Directory Structure
    # ========================================================================
    print("\n📂 Persistent Directories")
    print("-" * 60)

    dirs = ["trades", "data_cache", "backtest_results", "charts", "logs"]
    for dir_name in dirs:
        dir_path = Path(dir_name)
        exists = dir_path.exists()
        writable = dir_path.exists() and os.access(dir_path, os.W_OK)
        check(writable, f"  {dir_name}/ (writable)")
        if exists and not writable:
            warnings.append(f"Directory not writable: {dir_name}/")

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "="*60)
    print("Summary")
    print("="*60)

    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for error in errors:
            print(f"  • {error}")

    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings:
            print(f"  • {warning}")

    if not errors and not warnings:
        print("\n✅ All checks passed! Ready for deployment.\n")
        return 0

    if not errors:
        print("\n⚠️  Some optional checks failed, but should still work.\n")
        return 0

    print("\n❌ DEPLOYMENT BLOCKED - Fix errors above.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
