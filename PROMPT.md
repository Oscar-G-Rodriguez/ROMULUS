@plan.md @activity.md @PRD.md

You are building the ROMULUS Phase A backtesting engine according to the specifications in `PRD.md`.

## Your Process (Each Iteration)

1. **Read `activity.md`** to see what was recently accomplished
2. **Read `plan.md`** and find the SINGLE next task where `"passes": false`
3. **Implement that ONE task completely** following all steps listed
4. **Run tests** (if the task includes test steps)
5. **Verify success** - all tests pass, no errors
6. **Update `plan.md`** - change ONLY that task's `"passes"` from `false` to `true`
7. **Log to `activity.md`** - append a dated entry describing:
   - Which task you completed
   - What you implemented
   - Which tests you ran (copy/paste results)
   - Any issues encountered
8. **Make ONE git commit** with message format: `feat(category): description`
   - Example: `feat(setup): initialize project structure and dependencies`
   - Do NOT run `git init` (already done)
   - Do NOT run `git push` (local only)
   - Do NOT change git remotes

## Critical Rules

- ✅ Work on EXACTLY ONE task per iteration
- ✅ Complete ALL steps in that task before moving on
- ✅ Run all tests specified in the task steps
- ✅ Only modify `"passes"` field in plan.md (false → true)
- ✅ Do NOT remove or rewrite tasks in plan.md
- ✅ Do NOT skip tasks (they have dependencies)
- ✅ Make ONE commit per task (not per step)

## When Tests Fail

If tests fail:
1. Read the error message carefully
2. Fix the implementation
3. Re-run tests
4. Only mark `"passes": true` when ALL tests pass

## When You Encounter Errors

- Network errors with yfinance: Retry once, if still fails note in activity.md
- Import errors: Check dependencies installed correctly
- Path errors: Verify directory structure matches plan
- Test errors: Fix code until tests pass

## Completion

When ALL tasks in plan.md have `"passes": true`, output exactly:

```
<promise>COMPLETE</promise>
```

Do NOT output this promise until every single task is marked passing.

## Style Guidelines

- Use type hints in all Python functions
- Follow PEP 8 style guide
- Write clear docstrings for classes and functions
- Use descriptive variable names
- Keep functions focused and small
- Add comments for complex logic

## Testing Guidelines

- Run pytest with `-v` flag for verbose output
- If a test fails, show the full error trace
- Don't mark a task as passing if any test fails
- Use fixtures where appropriate
- Test edge cases (empty lists, zero values, boundary conditions)

## File Organization

- All Python files need `__init__.py` in their directories
- Config files go in `configs/`
- Tests go in `tests/unit/` or `tests/integration/`
- Source code goes in `romulus/`
- Never put source code in tests/ directory

## Dependencies

Already specified in plan.md task 1. Key packages:
- pandas, numpy (data manipulation)
- yfinance (data fetching)
- pydantic (config validation)
- pyarrow (Parquet I/O)
- click (CLI)
- pytest (testing)
- pandas-market-calendars (trading calendar)
- pyyaml (YAML configs)

Install with: `pip install -e .` after creating pyproject.toml

## Important Implementation Notes

### For inception gating (task: data/universe):
- Compare dates properly: `as_of_date >= inception_date`
- Return empty list if as_of_date before earliest inception

### For calendar (task: calendar):
- Use `pandas_market_calendars.get_calendar('NYSE')`
- Filter by weekday: `day.weekday() in [2, 4]` for Wed/Fri
- Convert to date objects consistently

### For portfolio (task: portfolio):
- Cash must be exact (use Decimal if needed, or careful float arithmetic)
- Support fractional shares (positions are floats, not ints)
- Apply costs correctly: net_cost = gross_value + commission + slippage_cost

### For backtest engine (task: backtest):
- Decision prices = close on decision_date
- Fill prices = open on fill_date (next trading day)
- Never use future data in strategy.compute_target_weights()
- Save outputs with deterministic run_id

## Git Workflow

```bash
# After completing a task:
git add .
git commit -m "feat(category): task description"

# Do NOT push (local only)
# Do NOT run git init (already initialized)
```

## Example Activity Log Entry

```markdown
### 2025-01-19 14:30 - Task Completed: setup/Initialize project structure

**Completed Steps:**
- Created directory structure: romulus/{data,calendar,portfolio,strategy,backtest,config,cli}
- Created tests/{unit,integration}
- Created configs/, data/cache/, outputs/runs/
- Created pyproject.toml with all dependencies
- Created .gitignore
- Ran: pip install -e .

**Tests Run:**
```bash
$ python -c 'import pandas, numpy, yfinance, pydantic, pyarrow, click, pytest'
# No errors - all imports successful
```

**Status:** ✅ All steps completed, all imports working

**Updated plan.md:** Task "setup/Initialize project structure" marked as passing
```

---

**Now begin with the first task in plan.md where "passes": false**
