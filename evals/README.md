# Evals

CodeMuse includes a deterministic 68-case baseline suite for local and CI regression.

The suite currently covers:

- tool selection and file operations
- approval integrity, stale previews, and side-effect policy
- checkpoint rewind and session recovery
- project/blueprint memory and recall
- repository analysis, import planning, and project planning
- bounded SubAgent execution and tool isolation
- guarded web fetch, search routing, and Browser safety
- capability catalog, Skill, and declarative Extension runtime
- MCP tool/resource/prompt discovery and invocation
- packaged end-to-end demo behavior

Run:

```powershell
python scripts\run_eval.py --output evals\reports
python scripts\run_agent.py benchmark run --output evals\reports
python scripts\run_agent.py doctor --run-eval --eval-output evals\reports
```

Latest report:

```text
evals/reports/latest.json
evals/reports/latest.md
```

The report layer also maintains an index, trend data/SVG, provider comparison metadata, and failure taxonomy. Live-provider checks remain separate because they require external credentials and network access.
