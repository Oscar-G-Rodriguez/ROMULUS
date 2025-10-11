"""
Train Selection Models that map value-model predictions → realized alpha decisions.

Inputs
- Value champions manifest: data/registry/champions.json
- OOF predictions from value champions: data/processed/oof/<tf>/<family>__<paramhash>.parquet
- Labels (realized alpha): data/processed/labels/<decision_tf>/<TICKER>.parquet
- CV splits for decision_tf: data/processed/cv/<decision_tf>/splits.json
- Tournament config (selection grids): config/tournament.yaml (selection.*)

Behavior
- Build a feature panel by joining per-timeframe champion predictions for each (timestamp,ticker).
  Feature names: pred_<tf>
- Target: labels[selection.target] on the decision timeframe (e.g., "y_alpha_p1")
- Train multiple selection challengers (LR/GB with param grids or random search)
- Save models + OOF preds + metrics

Outputs
- Models: data/models/selection/<decision_tf>/<family>__<param_id>.pkl
- OOF:    data/processed/selection_oof/<decision_tf>/<family>__<param_id>.parquet
- Metrics: data/results/selection_metrics/<decision_tf>/metrics.jsonl
"""

import os
import json
import itertools
import random
from typing import Dict, Any, List, Iterable, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet
from sklearn.ensemble import GradientBoostingRegressor

from ...utils.io_utils import (
    load_configs, load_yaml, ensure_dir, append_jsonl, dict_sha256
)
from ...utils.metrics import information_coefficient, rmse

CHAMPIONS_PATH   = "data/registry/champions.json"
OOF_ROOT         = "data/processed/oof"
LABEL_ROOT       = "data/processed/labels"
CV_ROOT          = "data/processed/cv"
SEL_MODEL_ROOT   = "data/models/selection"
SEL_OOF_ROOT     = "data/processed/selection_oof"
SEL_METRICS_DIR  = "data/results/selection_metrics"

def _cfg_global(cfg: Dict[str, Any]) -> Dict[str, Any]:
    sel = (cfg.get("selection") or {})
    decision_tf = sel.get("decision_timeframe", "1w")
    target = sel.get("target", "y_alpha_p1")
    n_jobs = int(sel.get("n_jobs", -1))  # not used by these models, but reserved
    return {"decision_tf": decision_tf, "target": target, "n_jobs": n_jobs}

def _cfg_tourney() -> Dict[str, Any]:
    t = load_yaml("config/tournament.yaml")
    s = (t.get("selection") or {})
    fams = [f.upper() for f in s.get("families", ["LR", "GB"])]
    search = s.get("search", {}) or {}
    grids = s.get("grids", {}) or {}
    return {
        "families": fams,
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
    values = [[(None if v in (None, "null") else v) for v in arr] for arr in values]
    if strategy == "grid":
        for combo in itertools.product(*values):
            yield {k: v for k, v in zip(keys, combo)}
    else:
        rnd = random.Random(rs)
        seen = set()
        trials = 0
        while trials < max_trials:
            combo = tuple(values[i][rnd.randrange(len(values[i]))] for i in range(len(keys)))
            if combo in seen:
                continue
            seen.add(combo)
            trials += 1
            yield {k: v for k, v in zip(keys, combo)}

def _load_champions() -> Dict[str, Any]:
    if not os.path.exists(CHAMPIONS_PATH):
        return {}
    with open(CHAMPIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f) or {}

def _load_value_oof(tf: str, fam_pid: str) -> pd.DataFrame:
    path = os.path.join(OOF_ROOT, tf, f"{fam_pid}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df["ticker"] = df["ticker"].str.upper()
    return df.rename(columns={"pred": f"pred_{tf}"})

def _load_labels(decision_tf: str) -> pd.DataFrame:
    d = os.path.join(LABEL_ROOT, decision_tf)
    if not os.path.isdir(d):
        return pd.DataFrame()
    frames = []
    for f in os.listdir(d):
        if not f.endswith(".parquet"):
            continue
        t = f[:-8].upper()
        df = pd.read_parquet(os.path.join(d, f))
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df["ticker"] = t
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_by = out.sort_values(["timestamp","ticker"]).reset_index(drop=True)
    return out

def _load_splits(decision_tf: str) -> List[Dict[str, Any]]:
    p = os.path.join(CV_ROOT, decision_tf, "splits.json")
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get("splits", [])

def _build_panel(decision_tf: str, champions: Dict[str, Any], target: str) -> Tuple[pd.DataFrame, List[str]]:
    # Join champions’ OOF preds across all timeframes onto the labels of decision_tf.
    lab = _load_labels(decision_tf)
    if lab.empty or target not in lab.columns:
        return pd.DataFrame(), []
    panel = lab[["timestamp","ticker",target]].copy()

    used_tfs = []
    for tf, meta in champions.items():
        fam_pid = f"{meta['family']}__{meta['param_id']}"
        oof = _load_value_oof(tf, fam_pid)
        if oof.empty:
            continue
        panel = panel.merge(oof[["timestamp","ticker",f"pred_{tf}"]], on=["timestamp","ticker"], how="left")
        used_tfs.append(tf)

    # Drop rows without any prediction features
    pred_cols = [c for c in panel.columns if c.startswith("pred_")]
    panel = panel.dropna(subset=pred_cols, how="all")
    return panel, pred_cols

def _build_model(family: str, params: Dict[str, Any]):
    if family == "LR":
        return ElasticNet(
            alpha=float(params.get("alpha", 0.001)),
            l1_ratio=float(params.get("l1_ratio", 0.5)),
            random_state=42
        )
    if family == "GB":
        return GradientBoostingRegressor(
            n_estimators=int(params.get("n_estimators", 400)),
            learning_rate=float(params.get("learning_rate", 0.05)),
            max_depth=int(params.get("max_depth", 3)),
            subsample=float(params.get("subsample", 1.0)),
            random_state=42
        )
    raise ValueError(f"Unknown selection family: {family}")

def main() -> None:
    cfg = load_configs()
    g = _cfg_global(cfg)
    t = _cfg_tourney()
    decision_tf = g["decision_tf"]
    target = g["target"]

    champions = _load_champions()
    if not champions:
        print("No champions.json found (value models).")
        return

    panel, pred_cols = _build_panel(decision_tf, champions, target)
    if panel.empty:
        print(f"No selection training panel for {decision_tf}.")
        return

    splits = _load_splits(decision_tf)
    if not splits:
        print(f"No CV splits for selection at {decision_tf}.")
        return

    X_all = panel[pred_cols].astype(float)
    y_all = panel[target].astype(float)
    ts = pd.to_datetime(panel["timestamp"]).dt.tz_localize(None)

    out_models = os.path.join(SEL_MODEL_ROOT, decision_tf)
    out_oof    = os.path.join(SEL_OOF_ROOT, decision_tf)
    out_metrics= os.path.join(SEL_METRICS_DIR, decision_tf)
    ensure_dir(out_models); ensure_dir(out_oof); ensure_dir(out_metrics)

    for family in t["families"]:
        grid = t["grids"].get(family, {})
        for params in _param_grid_iter(grid, t["search"]["strategy"], t["search"]["max_trials"], t["search"]["random_state"]):
            model = _build_model(family, params)
            pid = dict_sha256({"family": family, "params": params})[:12]

            oof = pd.Series(index=panel.index, dtype=float)
            fold_metrics = []

            for i, s in enumerate(splits, 1):
                tr = (ts >= pd.to_datetime(s["train_start"])) & (ts <= pd.to_datetime(s["train_end"]))
                te = (ts >= pd.to_datetime(s["test_start"]))  & (ts <= pd.to_datetime(s["test_end"]))
                X_tr, y_tr = X_all[tr], y_all[tr]
                X_te, y_te = X_all[te], y_all[te]
                if len(X_tr) < 100 or len(X_te) < 20:
                    continue
                model.fit(X_tr, y_tr)
                y_hat = pd.Series(model.predict(X_te), index=y_all[te].index)

                ic = information_coefficient(y_te, y_hat, method="spearman")
                e  = rmse(y_te, y_hat)
                fold_metrics.append({
                    "fold": i, "IC": None if pd.isna(ic) else float(ic),
                    "RMSE": None if pd.isna(e) else float(e),
                    "n_train": int(len(X_tr)), "n_test": int(len(X_te)),
                })
                oof.loc[y_hat.index] = y_hat.values

            # Refit on full data for artifact
            try:
                model.fit(X_all, y_all)
            except Exception:
                pass

            # Save artifacts
            import joblib
            model_path = os.path.join(out_models, f"{family}__{pid}.pkl")
            joblib.dump(model, model_path)

            oof_df = panel[["timestamp","ticker"]].copy()
            oof_df["pred"] = oof.values
            oof_path = os.path.join(out_oof, f"{family}__{pid}.parquet")
            oof_df.to_parquet(oof_path, index=False)

            avg_ic = float(np.nanmean([m["IC"] for m in fold_metrics])) if fold_metrics else np.nan
            avg_rmse = float(np.nanmean([m["RMSE"] for m in fold_metrics])) if fold_metrics else np.nan
            rec = {
                "timeframe": decision_tf,
                "family": family,
                "param_id": pid,
                "params": params,
                "features": pred_cols,
                "target": target,
                "avg_IC": None if pd.isna(avg_ic) else avg_ic,
                "avg_RMSE": None if pd.isna(avg_rmse) else avg_rmse,
                "model_path": model_path,
                "oof_path": oof_path,
                "folds": fold_metrics,
            }
            append_jsonl(os.path.join(SEL_METRICS_DIR, decision_tf, "metrics.jsonl"), rec)
            print(f"[selection {decision_tf}][{family}][{pid}] avg_IC={avg_ic:.4f} avg_RMSE={avg_rmse:.6f}")

    print("Selection training complete.")

main()
