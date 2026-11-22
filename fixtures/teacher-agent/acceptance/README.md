# Paper query acceptance

From the repository root, run:

```sh
backend/.venv/bin/python fixtures/teacher-agent/acceptance/run_acceptance.py --commit HEAD
```

Install the backend dependencies in `backend/.venv`, the frontend dependencies in `frontend/node_modules`, and Playwright with Chromium. The runner uses Bun's global Node modules for Playwright by default. Set `PLAYWRIGHT_NODE_PATH` if Playwright is installed elsewhere.

Start the local model provider before running. The default InnoAgent runtime is `../inno-agent-audit-20261015` and the default provider configuration is `runtime/innoagent/config/config.json`. Override them with `--runtime` and `--provider-config`. InnoAgent needs its built server, installed Node dependencies, and `pi-mcp-adapter`. The configured provider URL must be loopback.

The runner builds React and starts FastAPI from the selected commit with an isolated InnoAgent home and SQLite database. The test clock is November 22, 2026 at 12:00 UTC. Before opening Chromium, a direct SQLite query reads effective supervision and approved effective paper archives to compute the expected annual groups, student counts, and full doctoral published roster. The seed includes two distinct submissions with the same title, owner, and publication date.

The browser submits both questions, clicks the doctoral published group, and compares each drill submission ID, title, and owner in the API and UI. It repeats the comparison after page reload and conversation refresh. Aggregate cards are checked against the requested projection. The existing named query, revocation, manager isolation, and student guide checks also run.

The runner prints a new evidence directory with browser logs, check results, screenshots, and `run-summary.json`. Use `--output` with a new path to choose its location. The run uses synthetic records and keeps credentials and provider configuration in the temporary runtime.
