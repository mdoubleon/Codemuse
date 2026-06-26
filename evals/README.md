# Evals

Stage 28 introduced the first CodeMuse baseline eval suite.

The suite currently covers:

- file inspection
- file read
- approval-gated writes and replacements
- blocked shell safety
- checkpoint rewind
- project memory save/search
- subagent limited tools
- guarded web fetch blocking
- repository import planning
- blueprint-derived project planning
- minimal Web UI smoke coverage
- capability catalog skill/extension discovery
- mock MCP capability discovery

Run:

```powershell
python scripts\run_eval.py --output evals\reports
```

Latest report:

```text
evals/reports/latest.json
evals/reports/latest.md
```

This suite is deterministic and intended for local/CI regression. Future stages can add live-model eval mode, larger case datasets, charts, trend reports, and provider comparisons.
