"""Check if required packages are available."""
import sys

packages = [
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("yfinance", "yfinance"),
    ("pydantic", "pydantic"),
    ("pyarrow", "pyarrow"),
    ("click", "click"),
    ("pytest", "pytest"),
    ("pandas_market_calendars", "pandas-market-calendars"),
    ("yaml", "pyyaml"),
]

missing = []
for import_name, package_name in packages:
    try:
        __import__(import_name)
        print(f"OK: {package_name}")
    except ImportError:
        print(f"MISSING: {package_name}")
        missing.append(package_name)

if missing:
    print(f"\nMissing packages: {', '.join(missing)}")
    print(f"Install with: pip install {' '.join(missing)}")
    sys.exit(1)
else:
    print("\nAll imports successful!")
    sys.exit(0)
