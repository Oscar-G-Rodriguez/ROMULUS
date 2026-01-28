# RALPH - Autonomous Agent Loop for ROMULUS Build (Windows)
# Usage: .\ralph.ps1 -MaxIterations 25

param(
    [Parameter(Mandatory=$true)]
    [int]$MaxIterations
)

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "RALPH - ROMULUS Build Agent" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Max iterations: $MaxIterations"
Write-Host "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

for ($i = 1; $i -le $MaxIterations; $i++) {
    Write-Host "=========================================" -ForegroundColor Yellow
    Write-Host "Iteration $i / $MaxIterations" -ForegroundColor Yellow
    Write-Host "=========================================" -ForegroundColor Yellow
    Write-Host ""
    
    # Read PROMPT.md content
    $promptContent = Get-Content -Path "PROMPT.md" -Raw
    
    # Run Claude Code with PROMPT.md content
    $result = claude -p $promptContent --output-format text 2>&1 | Out-String
    
    Write-Host $result
    Write-Host ""
    
    # Check for completion promise
    if ($result -match "<promise>COMPLETE</promise>") {
        Write-Host "=========================================" -ForegroundColor Green
        Write-Host "✅ BUILD COMPLETE!" -ForegroundColor Green
        Write-Host "=========================================" -ForegroundColor Green
        Write-Host "All tasks completed after $i iterations."
        Write-Host "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Write-Host ""
        Write-Host "Next steps:"
        Write-Host "  1. Review outputs: cat activity.md"
        Write-Host "  2. Run tests: pytest tests/ -v"
        Write-Host "  3. Run backtest: python -m romulus.cli.main run --config configs/etf_equal_weight.yaml"
        Write-Host ""
        exit 0
    }
    
    # Check for errors
    if ($result -match "error|Error|ERROR") {
        Write-Host "⚠️  Warning: Iteration $i encountered errors" -ForegroundColor Red
        Write-Host "Check activity.md for details"
    }
    
    Write-Host ""
    Write-Host "--- End of iteration $i ---"
    Write-Host ""
    
    # Brief pause between iterations
    Start-Sleep -Seconds 2
}

Write-Host "=========================================" -ForegroundColor Red
Write-Host "⚠️  REACHED MAX ITERATIONS" -ForegroundColor Red
Write-Host "=========================================" -ForegroundColor Red
Write-Host "Completed $MaxIterations iterations"
Write-Host "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""
Write-Host "Build may not be complete. Check progress:"
Write-Host "  - Review: cat activity.md"
Write-Host "  - Check remaining tasks: Select-String -Path plan.md -Pattern '`"passes`": false'"
Write-Host ""
Write-Host "To continue, run: .\ralph.ps1 -MaxIterations 10"
Write-Host ""

exit 1