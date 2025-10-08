"""
Train cross-sectional challengers per timeframe using time-based CV splits.
Generates multiple challengers per model family by iterating param grids (grid or random).

Inputs
- Features (selected, normalized): data/processed/features_sel/<tf>/<TICKER>.parquet
- Labels:                            data/processed/labels/<tf>/<TICKER>.parquet
- CV splits:                         data/processed/cv/<tf>/splits.json
- Tournament config:                 config/tournament.yaml (modeling.*)

Outputs (per (family, params))
- Model:        data/models/<tf>/<family>__<paramhash>.pkl
- OOF preds:    data/processed/oof/<tf>/<family>__<paramhash>.parquet
- Metrics log:  data/results/metrics/<tf>/metrics.jsonl (one row per challenger)
"""

import os
import json
import itertools
import random
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Iterable

from ..utils.io_utils import load_configs, load_yaml, ensure_dir, append_jsonl, dict_sha256, set_global_seed
from ..utils.metrics import information_coefficient, rmse

# Optional model families
HAVE_XGB = False
HAVE_LGB = False
try:
    from xgboost import XGBRegressor
    HAVE_XGB = True
except Exception:
    pass
try:
    from lightgbm import LGBMRegressor
    HAVE_LGB = True
except Exception:
    pass

from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNet

FEAT_ROOT   = "data/processed/features_sel"
LABEL_ROOT  = "data/processed/labels"
CV_ROOT     = "data/processed/cv"
MODEL_ROOT  = "data/models"
OOF_ROOT    = "data/processed/oof"
METRICS_DIR = "data/results/metrics"


def _cfg_global(cfg: Dict[str, Any]) -> Dict[str, Any]:
    m = (cfg.get("modeling") or {})
    target = m.get("target", "y_alpha_p1")
    n_jobs = int(m.get("n_jobs", -1))
    return {"target": target, "n_jobs": n_jobs}

def _cfg_tourney() -> Dict[str, Any]:
    t = load_yaml("config/tournament.yaml")
    m = (t.get("modeling") or {})
    fams = [f.upper() for f in m.get("families", ["RF", "XGB", "LGB", "EN"])]
    search = m.get("search", {}) or {}
    grids = m.get("grids", {}) or {}
    # filter by availability
    avail = []
    for f in fams:
        if f == "RF":
            avail.append("RF")
        elif f == "EN":
            avail.append("EN")
        elif f == "XGB" and HAVE_XGB:
            avail.append("XGB")
        elif f == "LGB" and HAVE_LGB:
            avail.append("LGB")
    if not avail:
        avail = ["RF", "EN"]
    return {
        "families": avail,
        "search": {
            "strategy": search.get("strategy", "grid"),
            "max_trials": int(search.get("max_trials", 12)),
            "random_state": int(search.get("random_state", 42)),
        },
        "grids": grids,
    }

def _param_grid_iter(grid: Dict[str, List[Any]], strategy: str, max_trials: int, rs: int) -> Iterable[Dict[str, Any]]:
    if not grid:
        yield {}
        return
    keys = sorted(grid.keys())
    values = [grid[k] for k in keys]
    # normalize None/null values
    values = [[(None if v in (None, "null") else v) for v in arr] for arr in values]
    if strategy == "grid":
        for combo in itertools.product(*values):
            yield {k: v for k, v in zip(keys, combo)}
    else:
        rnd = random.Random(rs)
        # flat sample space
        choices = [list(arr) for arr in values]
        seen = set()
        trials = 0
        while trials < max_trials:
            combo = tuple(choices[i][rnd.randrange(len(choices[i]))] for i in range(len(keys)))
            if combo in seen:
                continue
            seen.add(combo)
            trials += 1
            yield {k: v for k, v in zip(keys, combo)}

def _list_tickers(dir_path: str) -> List[str]:
    return [f[:-8].upper() for f in os.listdir(dir_path) if f.endswith(".parquet")]

def _load_panel(tf: str) -> Tuple[pd.DataFrame, List[str]]:
    feat_dir = os.path.join(FEAT_ROOT, tf)
    lab_dir  = os.path.join(LABEL_ROOT, tf)
    if not (os.path.exists(feat_dir) and os.path.exists(lab_dir)):
        return pd.DataFrame(), []
    tickers = sorted(set(_list_tickers(feat_dir)).intersection(_list_tickers(lab_dir)))
    frames = []
    for t in tickers:
        xf = pd.read_parquet(os.path.join(feat_dir, f"{t}.parquet"))
        yl = pd.read_parquet(os.path.join(lab_dir,  f"{t}.parquet"))
        df = xf.merge(yl, on=["timestamp","ticker"], how="inner")
        df["ticker"] = t
        frames.append(df)
    if not frames:
        return pd.DataFrame(), []
    panel = pd.concat(frames, ignore_index=True)
    panel["timestamp"] = pd.to_datetime(panel["timestamp"]).dt.tz_localize(None)
    panel = panel.sort_values(["timestamp","ticker"]).reset_index(drop=True)
    return panel, tickers

def _load_splits(tf: str) -> List[Dict[str, Any]]:
    path = os.path.join(CV_ROOT, tf, "splits.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get("splits", [])

def _build_model(family: str, params: Dict[str, Any], n_jobs: int, rs: int):
    if family == "RF":
        return RandomForestRegressor(
            n_estimators=int(params.get("n_estimators", 400)),
            max_depth=None if params.get("max_depth") in (None, "None") else params.get("max_depth"),
            min_samples_leaf=int(params.get("min_samples_leaf", 2)),
            random_state=rs, n_jobs=n_jobs
        )
    if family == "EN":
        return ElasticNet(
            alpha=float(params.get("alpha", 0.001)),
            l1_ratio=float(params.get("l1_ratio", 0.5)),
            random_state=rs
        )
    if family == "XGB" and HAVE_XGB:
        return XGBRegressor(
            n_estimators=int(params.get("n_estimators", 600)),
            max_depth=int(params.get("max_depth", 6)),
            learning_rate=float(params.get("learning_rate", 0.05)),
            subsample=float(params.get("subsample", 0.7)),
            colsample_bytree=float(params.get("colsample_bytree", 0.7)),
            random_state=rs, n_jobs=max(1, n_jobs)
        )
    if family == "LGB" and HAVE_LGB:
        return LGBMRegressor(
            n_estimators=int(params.get("n_estimators", 800)),
            num_leaves=int(params.get("num_leaves", 31)),
            learning_rate=float(params.get("learning_rate", 0.05)),
            subsample=float(params.get("subsample", 0.7)),
            colsample_bytree=float(params.get("colsample_bytree", 0.7)),
            random_state=rs, n_jobs=max(1, n_jobs)
        )
    raise ValueError(f"Unknown or unavailable family: {family}")

def _feature_columns(df: pd.DataFrame, target: str) -> List[str]:
    ignore = {"timestamp", "ticker", target}
    return [c for c in df.columns if c not in ignore and not c.startswith("y_")]

def main() -> None:
    # Load both global config and tournament config
    base_cfg = load_configs()
    cfg_global = _cfg_global(base_cfg)
    cfg_tour = _cfg_tourney()

    set_global_seed(cfg_tour["search"]["random_state"])

    if not os.path.exists(FEAT_ROOT):
        print(f"No features at {FEAT_ROOT}.")
        return
    tfs = [d for d in os.listdir(FEAT_ROOT) if os.path.isdir(os.path.join(FEAT_ROOT, d))]

    for tf in tfs:
        panel, tickers = _load_panel(tf)
        if panel.empty:
            print(f"Skip {tf}: no panel")
            continue

        splits = _load_splits(tf)
        if not splits:
            print(f"Skip {tf}: no CV splits")
            continue

        target = cfg_global["target"]
        if target not in panel.columns:
            print(f"Skip {tf}: target {target} not found")
            continue

        feat_cols = _feature_columns(panel, target)
        if not feat_cols:
            print(f"Skip {tf}: no feature columns")
            continue

        X_all = panel[feat_cols].astype(float).copy()
        y_all = panel[target].astype(float).copy()
        ts_all = pd.to_datetime(panel["timestamp"]).dt.tz_localize(None)

        ensure_dir(os.path.join(MODEL_ROOT, tf))
        ensure_dir(os.path.join(OOF_ROOT, tf))
        ensure_dir(os.path.join(METRICS_DIR, tf))

        for family in cfg_tour["families"]:
            grid = cfg_tour["grids"].get(family, {})
            strategy = cfg_tour["search"]["strategy"]
            max_trials = cfg_tour["search"]["max_trials"]
            rs = cfg_tour["search"]["random_state"]

            for params in _param_grid_iter(grid, strategy, max_trials, rs):
                # Build model for this challenger
                model = _build_model(family, params, cfg_global["n_jobs"], rs)

                # Param hash for artifact names
                pid = dict_sha256({"family": family, "params": params})[:12]
                model_path = os.path.join(MODEL_ROOT, tf, f"{family}__{pid}.pkl")
                oof_path = os.path.join(OOF_ROOT, tf, f"{family}__{pid}.parquet")

                # OOF container and fold metrics
                oof = pd.Series(index=panel.index, dtype=float)
                fold_metrics = []

                for i, s in enumerate(splits, 1):
                    tr_mask = (ts_all >= pd.to_datetime(s["train_start"])) & (ts_all <= pd.to_datetime(s["train_end"]))
                    te_mask = (ts_all >= pd.to_datetime(s["test_start"]))  & (ts_all <= pd.to_datetime(s["test_end"]))

                    X_tr, y_tr = X_all[tr_mask], y_all[tr_mask]
                    X_te, y_te = X_all[te_mask], y_all[te_mask]
                    if len(X_tr) < 100 or len(X_te) < 20:
                        continue

                    model.fit(X_tr, y_tr)
                    y_hat = pd.Series(model.predict(X_te), index=y_all[te_mask].index)

                    ic = information_coefficient(y_te, y_hat, method="spearman")
                    e  = rmse(y_te, y_hat)
                    fold_metrics.append({
                        "fold": i,
                        "IC": None if pd.isna(ic) else float(ic),
                        "RMSE": None if pd.isna(e) else float(e),
                        "n_train": int(len(X_tr)),
                        "n_test": int(len(X_te)),
                    })
                    oof.loc[y_hat.index] = y_hat.values

                # Fit on full data at end for artifact
                try:
                    model.fit(X_all, y_all)
                except Exception:
                    pass
                joblib.dump(model, model_path)

                # Save OOF predictions
                oof_df = panel[["timestamp","ticker"]].copy()
                oof_df["pred"] = oof.values
                oof_df.to_parquet(oof_path, index=False)

                # Aggregate metrics
                avg_ic = float(np.nanmean([m["IC"] for m in fold_metrics])) if fold_metrics else np.nan
                avg_rmse = float(np.nanmean([m["RMSE"] for m in fold_metrics])) if fold_metrics else np.nan

                record = {
                    "timeframe": tf,
                    "family": family,
                    "params": params,
                    "param_id": pid,
                    "target": target,
                    "features": feat_cols,
                    "folds": fold_metrics,
                    "avg_IC": None if pd.isna(avg_ic) else avg_ic,
                    "avg_RMSE": None if pd.isna(avg_rmse) else avg_rmse,
                    "model_path": model_path,
                    "oof_path": oof_path,
                }
                append_jsonl(os.path.join(METRICS_DIR, tf, "metrics.jsonl"), record)
                print(f"[{tf}][{family}][{pid}] avg_IC={avg_ic:.4f} avg_RMSE={avg_rmse:.6f}")

    print("Training complete.")


main()
