# Desktop Application Guide

Launch with `uv run romulus ui`.

## 1. Prepare data and dates

Choose Synthetic for an offline demonstration, Cache to prohibit downloads, or yfinance for explicitly requested market history. Choose Dynamic or Common coverage, then select **Inspect Coverage**. The date controls stay disabled until inspection succeeds and contain only dates inside the verified bounds.

The advanced YAML editor exposes every engine option without requiring an external editor. Validate it before inspecting coverage; changes to the universe, source, or policy invalidate the prior coverage result.

## 2. Run and track location

The Run tab displays the current phase, current simulated decision date, completed/total decisions, active champion, overall percentage, elapsed-time-derived ETA, and console details. Progress counts scheduled events rather than calendar days. **Cancel Safely** stops at a decision boundary and produces a manifest marked `cancelled`.

## 3. Read results

Overview compares the normalized portfolio paths and summary metrics. Champion Timeline shows every decision and identifies actual Friday switches. ML Accuracy exposes mature-label diagnostics rather than training fit. Runs reopens any stored artifact set.

## 4. Audit one decision

Select a Champion Timeline row. Decision Audit shows:

1. Market regime and its as-of inputs.
2. Every candidate’s rolling metrics, normalized components, gates, and rank.
3. Incumbent, challenger, margin, winner, and explanation.
4. The selected strategy’s signals or ML forecasts and target weights.
5. Meta orders/fills, costs, cash, positions, and resulting portfolio value.

This drill-down is the fastest way to answer “what did ROMULUS choose that week, and why?”

