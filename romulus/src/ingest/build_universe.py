"""
Online universe builder (no local CSV needed).

Sources (no API keys):
  1) NASDAQ Trader symbol directories:
     - https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt
     - https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt
  2) SEC company tickers JSON:
     - https://www.sec.gov/files/company_tickers.json
  3) Wikipedia S&P 500 (seed / sanity):
     - https://en.wikipedia.org/wiki/List_of_S%26P_500_companies

Behavior:
  - Fetch from all available sources, merge, dedupe, uppercase tickers.
  - Attach sector/industry when provided by the source.
  - Optionally enrich with price/ADV via yfinance (if installed).
  - Apply filters from config (min_price, min_mktcap_usd, min_adv_20, ipo_exclusion_days)
    *only* where data is available; defer the rest.
  - Save PIT universe into config/universe.yaml and snapshot to data/meta/data_snapshots/.

Notes:
  - Public endpoints can throttle or change formats; we set a legit User-Agent.
  - yfinance enrichment is off by default to keep runtime fast.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from ..utils.io_utils import load_configs, save_yaml, ensure_dir, dict_sha256

# Optional enrichment
try:
    import yfinance as yf  # noqa: F401
    HAVE_YF = True
except Exception:
    HAVE_YF = False

try:
    import requests
    HAVE_REQ = True
except Exception:
    HAVE_REQ = False


UNIVERSE_OUT = "config/universe.yaml"
SNAPSHOT_DIR = "data/meta/data_snapshots"


def _http_get(url: str, timeout: int = 20) -> Optional[bytes]:
    if not HAVE_REQ:
        return None
    headers = {
        "User-Agent": "Romulus/1.0 (research; contact: romulus@example.com)",
        "Accept": "*/*",
        "Connection": "close",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception:
        return None


def _fetch_nasdaq_trader() -> pd.DataFrame:
    """
    Pull NASDAQ + OTHER listed symbols from NASDAQ Trader symdir.
    Format is pipe-delimited with a header/footer line.
    """
    urls = [
        "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
        "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
    ]
    frames = []
    for u in urls:
        raw = _http_get(u)
        if raw is None:
            continue
        # Decode, split, and read via pandas
        text = raw.decode("utf-8", errors="ignore").splitlines()
        # Drop footer lines containing "File Creation Time" etc.
        text = [ln for ln in text if "File Creation Time" not in ln and "Symbol|Security Name" not in ln and "ACT Symbol" not in ln]
        if "nasdaqlisted.txt" in u:
            cols = ["Symbol", "Security Name", "Market Category", "Test Issue", "Financial Status", "Round Lot Size", "ETF", "NextShares"]
        else:
            cols = ["ACT Symbol", "Security Name", "Exchange", "CQS Symbol", "ETF", "Round Lot Size", "Test Issue", "NASDAQ Symbol"]
        try:
            df = pd.read_csv(pd.compat.StringIO("\n".join(text)), sep="|", header=None, names=cols, dtype=str)
        except Exception:
            # Fallback using standard io
            from io import StringIO
            df = pd.read_csv(StringIO("\n".join(text)), sep="|", header=None, names=cols, dtype=str)

        # Normalize to a common schema
        if "Symbol" in df.columns:
            sym = df["Symbol"]
        elif "ACT Symbol" in df.columns:
            sym = df["ACT Symbol"]
        else:
            sym = pd.Series([], dtype=str)

        cur = pd.DataFrame({
            "ticker": sym.astype(str).str.upper().str.strip(),
            "name": df.get("Security Name"),
            "exchange": df.get("Market Category", df.get("Exchange")),
        })
        frames.append(cur)

    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "exchange"])
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["ticker"])
    out = out[~out["ticker"].str.contains(r"[\^\.]")]  # drop weird composite symbols
    out = out.drop_duplicates(subset=["ticker"]).reset_index(drop=True)
    return out


def _fetch_sec() -> pd.DataFrame:
    """Fetch SEC company tickers JSON; yields ticker + CIK + title."""
    url = "https://www.sec.gov/files/company_tickers.json"
    raw = _http_get(url)
    if raw is None:
        return pd.DataFrame(columns=["ticker", "name"])
    try:
        js = pd.read_json(raw)
        # SEC publishes as dict keyed by index; normalize
        if isinstance(js, pd.DataFrame) and {"cik_str", "ticker", "title"}.issubset(js.columns):
            df = js
        else:
            # If json loads as dict-of-dicts
            df = pd.DataFrame(js).T
        df["ticker"] = df["ticker"].astype(str).str.upper()
        df = df.rename(columns={"title": "name"})
        return df[["ticker", "name"]].drop_duplicates("ticker")
    except Exception:
        return pd.DataFrame(columns=["ticker", "name"])


def _fetch_sp500() -> pd.DataFrame:
    """Fetch S&P 500 constituents from Wikipedia as a small high-quality seed set."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    raw = _http_get(url)
    if raw is None:
        return pd.DataFrame(columns=["ticker", "name", "sector", "industry"])
    try:
        # Read tables with pandas; pick the first that has Symbol column
        from io import BytesIO
        tables = pd.read_html(BytesIO(raw))
        for tb in tables:
            if "Symbol" in tb.columns:
                df = tb.rename(columns={"Symbol": "ticker", "Security": "name", "GICS Sector": "sector", "GICS Sub-Industry": "industry"})
                df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
                return df[["ticker", "name", "sector", "industry"]]
        return pd.DataFrame(columns=["ticker", "name", "sector", "industry"])
    except Exception:
        return pd.DataFrame(columns=["ticker", "name", "sector", "industry"])


def _merge_sources() -> pd.DataFrame:
    """Combine NASDAQ Trader, SEC, and S&P 500 tables."""
    dfs = [_fetch_nasdaq_trader(), _fetch_sec(), _fetch_sp500()]
    base = pd.DataFrame(columns=["ticker", "name", "exchange", "sector", "industry"])
    for d in dfs:
        if d is None or d.empty:
            continue
        # Harmonize columns
        for col in ["ticker", "name", "exchange", "sector", "industry"]:
            if col not in d.columns:
                d[col] = None
        base = pd.concat([base, d[["ticker", "name", "exchange", "sector", "industry"]]], ignore_index=True)
    if base.empty:
        return base
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    base = base.dropna(subset=["ticker"])
    base = base.drop_duplicates(subset=["ticker"]).reset_index(drop=True)
    return base


def _optional_enrich_price_adv(df: pd.DataFrame, max_symbols: int = 1000) -> pd.DataFrame:
    """
    Optionally pull recent price and volume to estimate filters (min_price, min_adv_20).
    Limited to first `max_symbols` to keep runtime sane in V1.
    """
    if not HAVE_YF or df.empty:
        return df
    tickers = df["ticker"].tolist()[:max_symbols]
    out_rows = []
    for t in tickers:
        try:
            hist = pd.DataFrame(yf.Ticker(t).history(period="6mo", interval="1d"))
            if hist.empty:
                continue
            hist = hist.rename(columns=str.lower)
            last_price = float(hist["close"].dropna().iloc[-1])
            adv_20 = float(hist["volume"].dropna().tail(20).mean()) if "volume" in hist else None
            out_rows.append({"ticker": t, "price": last_price, "adv_20": adv_20})
        except Exception:
            continue
    if not out_rows:
        return df
    enrich = pd.DataFrame(out_rows)
    merged = df.merge(enrich, on="ticker", how="left")
    return merged


def _apply_filters(df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """
    Apply filters only when the needed fields exist. We won’t drop names just
    because a field (e.g., market_cap) is missing from public sources.
    """
    uni_root = cfg.get("universe", {})
    uni_cfg = uni_root.get("universe", uni_root)

    min_price = float(uni_cfg.get("min_price", 2.0))
    min_mktcap = float(uni_cfg.get("min_mktcap_usd", 5e8))
    min_adv = float(uni_cfg.get("min_adv_20", 1e6))
    ipo_exclusion_days = int(uni_cfg.get("ipo_exclusion_days", 60))

    out = df.copy()

    # Price filter when available
    if "price" in out.columns:
        out = out[out["price"].fillna(0) >= min_price]

    # ADV filter when available
    if "adv_20" in out.columns and min_adv > 0:
        out = out[out["adv_20"].fillna(0) >= min_adv]

    # IPO exclusion when we have first_trade_date (we don't from these sources).
    # Leave PIT dating to later if missing. We provide defaults below.

    # Defaults for PIT dating (until we have vendor-grade history)
    out["first_trade_date"] = pd.NaT
    out["delist_date"] = pd.NaT
    out["active_start"] = pd.Timestamp("1900-01-01")
    out["active_end"] = pd.Timestamp("2262-04-11")

    # Liquidity buckets unknown here. Mark as "B" by default; later stages can refine.
    out["liq_bucket"] = "B"

    # Keep a reasonable upper bound to avoid massive universes in V1
    # (adjust or remove once you’re comfortable with runtime)
    out = out.head(4000).reset_index(drop=True)

    return out


def _to_yaml_structure(df: pd.DataFrame, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the merged frame to config/universe.yaml structure."""
    uni_root = cfg.get("universe", {})
    uni_cfg = uni_root.get("universe", uni_root)

    tickers: List[str] = []
    meta: Dict[str, Dict[str, Any]] = {}

    for _, r in df.sort_values("ticker").iterrows():
        t = str(r["ticker"]).upper()
        tickers.append(t)
        meta[t] = {
            "sector": str(r.get("sector") or "Unknown"),
            "industry": str(r.get("industry") or "Unknown"),
            "liq_bucket": str(r.get("liq_bucket") or "B"),
            "active_start": str(pd.Timestamp(r.get("active_start")).date()),
            "active_end": str(pd.Timestamp(r.get("active_end")).date()),
        }

    out = {
        "universe": {
            "provider": uni_cfg.get("provider", "public_mix"),
            "include_delisted": True,
            "min_price": uni_cfg.get("min_price", 2.0),
            "min_mktcap_usd": uni_cfg.get("min_mktcap_usd", 5e8),
            "min_adv_20": uni_cfg.get("min_adv_20", 1e6),
            "ipo_exclusion_days": uni_cfg.get("ipo_exclusion_days", 60),
            "asof": datetime.utcnow().strftime("%Y-%m-%d"),
            "tickers": tickers,
            "metadata": meta,
        }
    }
    return out


def main() -> None:
    cfg = load_configs()

    # 1) Merge all public sources we can reach
    base = _merge_sources()
    if base.empty:
        raise RuntimeError("Failed to fetch listings from all public sources. Check network and try again.")

    # 2) Optional enrichment (last price / ADV via yfinance)
    #    Flip to True if you want immediate filtering by price/ADV based on recent data.
    ENRICH_WITH_YF = False
    if ENRICH_WITH_YF:
        base = _optional_enrich_price_adv(base, max_symbols=1000)

    # 3) Apply filters (only where fields exist)
    filtered = _apply_filters(base, cfg)

    # 4) Serialize to YAML and snapshot
    uni_yaml = _to_yaml_structure(filtered, cfg)
    save_yaml(uni_yaml, UNIVERSE_OUT)

    ensure_dir(SNAPSHOT_DIR)
    h = dict_sha256(uni_yaml)
    snap = os.path.join(SNAPSHOT_DIR, f"universe_{uni_yaml['universe']['asof']}_{h[:8]}.yaml")
    save_yaml(uni_yaml, snap)

    print(f"Wrote {UNIVERSE_OUT}")
    print(f"Snapshot: {snap}")


main()
