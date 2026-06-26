# Benchmarks

CodeMuse currently has a deterministic baseline benchmark/eval runner.

Run:

```powershell
python scripts\run_eval.py --output evals\reports
python scripts\run_agent.py benchmark run --output evals\reports
```

Run a subset:

```powershell
python scripts\run_eval.py --cases file_list,web_private_block
```

The runner uses `FakeLLM`, temporary workspaces, and fixed assertions. It does not call real model providers or real network resources.

Current report files:

```text
evals/reports/latest.json
evals/reports/latest.md
```

Implementation:

```text
src/codemuse/benchmarks/models.py
src/codemuse/benchmarks/report.py
src/codemuse/benchmarks/baseline.py
```
