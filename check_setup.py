#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify production setup is correctly installed.
Run this before deploying to production.
"""
import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

print("Testing Abroad Production Setup...\n")

errors = []
warnings = []

# Test 1: Core dependencies
print("[1] Checking core dependencies...")
core_deps = {
    "flask": "Flask web framework",
    "werkzeug": "WSGI utilities",
    "click": "CLI commands",
}

for dep, desc in core_deps.items():
    try:
        __import__(dep)
        print(f"   [OK] {dep}")
    except ImportError as e:
        errors.append(f"{dep}: {e}")
        print(f"   [FAIL] {dep} - {desc}")

# Test 2: Production dependencies (optional but recommended)
print("\n2️⃣  Checking production dependencies...")
prod_deps = {
    "redis": "Caching & sessions",
    "celery": "Background tasks",
    "sendgrid": "Email service",
    "twilio": "SMS service",
    "stripe": "Payment processing",
    "boto3": "AWS S3 storage",
    "marshmallow": "Input validation",
    "sentry_sdk": "Error monitoring",
}

for dep, desc in prod_deps.items():
    try:
        __import__(dep)
        print(f"   ✅ {dep}")
    except ImportError:
        warnings.append(f"{dep} - {desc}")
        print(f"   ⚠️  {dep} (optional: {desc})")

# Test 3: New modules
print("\n[3] Checking new production modules...")
new_modules = [
    ("config", "Configuration management"),
    ("health", "Health check endpoints"),
    ("webhooks", "Payment webhooks"),
    ("tasks", "Background tasks"),
    ("rate_limiting", "Rate limiting"),
    ("validation", "Input validation schemas"),
]

for mod, desc in new_modules:
    try:
        __import__(mod)
        print(f"   [OK] {mod}.py")
    except ImportError as e:
        errors.append(f"{mod}: {e}")
        print(f"   [FAIL] {mod}.py - {desc}")

# Test 4: Services
print("\n[4] Checking service modules...")
services = [
    "email_service",
    "sms_service",
    "payment_service",
    "storage_service",
]

for service in services:
    try:
        __import__(f"services.{service}")
        print(f"   [OK] services/{service}.py")
    except ImportError as e:
        errors.append(f"services.{service}: {e}")
        print(f"   [FAIL] services/{service}.py")

# Test 5: Middleware
print("\n[5] Checking middleware...")
middleware = [
    ("security", "Security headers"),
    ("logging_config", "Structured logging"),
]

for mid, desc in middleware:
    try:
        __import__(f"middleware.{mid}")
        print(f"   [OK] middleware/{mid}.py")
    except ImportError as e:
        errors.append(f"middleware.{mid}: {e}")
        print(f"   [FAIL] middleware/{mid}.py - {desc}")

# Test 6: Environment
print("\n[6] Checking environment configuration...")
if os.path.exists(".env"):
    print("   [OK] .env file exists")
else:
    warnings.append("No .env file (copy from .env.example)")
    print("   [WARN] .env not found (copy from .env.example)")

if os.path.exists(".env.example"):
    print("   [OK] .env.example exists")
else:
    errors.append(".env.example template missing")
    print("   [FAIL] .env.example missing")

# Test 7: App creation
print("\n7️⃣  Testing app creation...")
try:
    from app_production import create_app
    test_config = {
        "TESTING": True,
        "CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "AUTO_INIT": False,
    }
    app = create_app(test_config)
    print("   ✅ Production app created successfully")

    # Check blueprints
    blueprints = ["auth", "main", "health"]
    for bp in blueprints:
        if bp in app.blueprints:
            print(f"   ✅ Blueprint '{bp}' registered")
        else:
            warnings.append(f"Blueprint '{bp}' not registered")
            print(f"   ⚠️  Blueprint '{bp}' not found")

except Exception as e:
    errors.append(f"App creation failed: {e}")
    print(f"   ❌ App creation failed: {e}")

# Test 8: Original app (backward compatibility)
print("\n[8] Testing backward compatibility...")
try:
    from app import create_app as create_original_app
    app = create_original_app({"TESTING": True, "AUTO_INIT": False})
    print("   [OK] Original app still works")
except Exception as e:
    warnings.append(f"Original app: {e}")
    print(f"   [WARN] Original app: {e}")

# Summary
print("\n" + "="*60)
if errors:
    print(f"[FAIL] {len(errors)} CRITICAL ERROR(S):\n")
    for error in errors:
        print(f"   - {error}")
    print("\nFix: pip install -r requirements-production.txt")
    print("\nCannot run in production mode")
    exit_code = 1
else:
    print("[SUCCESS] All critical checks passed!")
    exit_code = 0

if warnings:
    print(f"\n[WARN] {len(warnings)} WARNING(S):\n")
    for warning in warnings:
        print(f"   - {warning}")
    print("\nOptional features - install for full functionality")

if exit_code == 0:
    print("\n[READY] Ready to run:")
    print("   python app_production.py")
    print("\nNext steps:")
    print("   1. Copy .env.example to .env")
    print("   2. Configure API keys in .env")
    print("   3. Run: python app_production.py")

sys.exit(exit_code)
