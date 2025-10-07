"""
Impute active_start/active_end in the universe metadata from saved price history.
This is a practical survivorship-bias guard when listing sources don't include PIT dates.

- Reads Parquets in data/raw/prices/1d/
- Finds first and last available bar per ticker
- Updates config/universe.yaml metadata accordingly (only fills missing/placeholder values)
"""

import os
import pandas as pd
from typing import Dict, Any

from ..utils.io_utils import load_configs, save_yaml

RAW_1D_DIR = "data/raw/prices/1d"
UNIVERSE_OUT = "config/universe.yaml"


def main() -> None:
    cfg = load_configs()
    uni_root = cfg.get("universe", {})
    uni = uni_root.get("universe", uni_root)
    meta: Dict[str, Dict[str, Any]] = uni.get("metadata", {})

    if not os.path.exists(RAW_1D_DIR):
        print(f"No daily raw price dir found at {RAW_1D_DIR}")
        return

    # For each parquet, compute first/last date
    updates = 0
    for fname in os.listdir(RAW_1D_DIR):
        if not fname.endswith(".parquet"):
            continue
        tkr = fname.replace(".parquet", "").upper()
        fp = os.path.join(RAW_1D_DIR, fname)
        try:
            df = pd.read_parquet(fp, columns=["timestamp"])
            if df.empty:
                continue
            first_dt = pd.to_datetime(df["timestamp"]).min().date()
            last_dt  = pd.to_datetime(df["timestamp"]).max().date()

            # Ensure metadata entry exists
            if tkr not in meta:
                meta[tkr] = {
                    "sector": "Unknown",
                    "industry": "Unknown",
                    "liq_bucket": "B",
                    "active_start": str(first_dt),
                    "active_end": str(last_dt),
                }
                updates += 1
                continue

            # Update only if missing or placeholder
            m = meta[tkr]
            if not m.get("active_start") or m["active_start"] == "1900-01-01":
                m["active_start"] = str(first_dt); updates += 1
            if not m.get("active_end") or m["active_end"] == "2262-04-11":
                m["active_end"] = str(last_dt); updates += 1

        except Exception as e:
            print(f"Skip {tkr}: {e}")

    # Write back
    uni["metadata"] = meta
    cfg["universe"] = {"universe": uni} if "universe" in uni_root else uni
    save_yaml({"universe": uni}, UNIVERSE_OUT)
    print(f"Imputed active windows for ~{updates} fields; wrote {UNIVERSE_OUT}")


main()
