# Agents Overview

This repository provides a set of **coding agents** designed to streamline development workflows, especially when used with the **OpenCode** environment. The agents defined here can be invoked directly via the command line or through automation scripts. They cover a range of tasks such as code generation, testing, linting, documentation, and CI/CD integration.

---

## Table of Contents

1. [General Principles](#general-principles)
2. [Agent Types](#agent-types)
   - [Code Generation Agent](#code-generation-agent)
   - [Testing Agent](#testing-agent)
   - [Linting & Formatting Agent](#linting--formatting-agent)
   - [Documentation Agent](#documentation-agent)
   - [CI/CD Agent](#cicd-agent)
   - [Review & Refactor Agent](#review--refactor-agent)
3. [Integration with OpenCode](#integration-with-opencode)
4. [Running Agents Locally](#running-agents-locally)
5. [Configuration](#configuration)
6. [Extending the Agent Suite](#extending-the-agent-suite)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)
9. [License](#license)

---

## General Principles

- **Single Responsibility** – Each agent performs one well‑defined function. This makes them composable and easier to test.
- **Idempotent Operations** – Agents should be safe to run multiple times without causing unintended side effects.
- **Minimal External Dependencies** – Prefer built‑in Node.js/Python modules or narrowly scoped npm packages.
- **Explicit I/O** – All inputs (flags, config files, stdin) and outputs (stdout, exit codes, generated files) are documented.
- **Fail Fast** – Agents exit with a non‑zero status code on error and provide concise diagnostic messages.
- **OpenCode Compatibility** – Agents are designed to work seamlessly with the OpenCode toolchain (e.g., `bash`, `git`, `gh`).

---

## Agent Types

### Code Generation Agent

**Purpose:** Scaffold new components, services, or pages based on templates.

**Command Example:**
```
./agents/generate.sh component Button --framework react --style css
```

**Features:**
- Template selection via `--type` (component, service, hook, etc.).
- Supports React, Vue, and vanilla JS/TS.
- Automatically registers the new artifact in the appropriate index file.
- Runs lint and type‑check after generation to ensure the scaffold is valid.

---

### Testing Agent

**Purpose:** Run unit, integration, and end‑to‑end tests with optional coverage reports.

**Command Example:**
```
./agents/test.sh --watch --coverage
```

**Supported Frameworks:**
- Jest (unit & integration)
- Playwright (E2E)
- Cypress (optional, if present)

**Outputs:**
- Human‑readable summary on stdout.
- `coverage/` directory when `--coverage` is used.
- JUnit XML report (`reports/junit.xml`) for CI pipelines.

---

### Linting & Formatting Agent

**Purpose:** Enforce code style and catch common bugs.

**Command Example:**
```
./agents/lint.sh --fix
```

**Tools Used:**
- ESLint (with project‑specific config)
- Prettier for formatting
- Stylelint for CSS/SCSS

**Exit Codes:**
- `0` – No lint errors (or all fixed when `--fix`).
- `1` – Lint errors remain.

---

### Documentation Agent

**Purpose:** Generate API docs, markdown reference files, and changelogs.

**Command Example:**
```
./agents/docs.sh --type api --output docs/api.md
```

**Capabilities:**
- Parse JSDoc/TSDoc comments to produce Markdown API docs.
- Create a `CHANGELOG.md` entry from conventional commit messages.
- Optionally update `README.md` sections (e.g., usage examples).

---

### CI/CD Agent

**Purpose:** Wire the repository into CI pipelines (GitHub Actions, GitLab CI, etc.).

**Command Example:**
```
./agents/ci.sh setup --provider github
```

**What It Does:**
- Generates `.github/workflows/ci.yml` with jobs for lint, test, build, and deploy.
- Adds required secrets placeholders.
- Optionally configures caching for `node_modules`.

---

### Review & Refactor Agent

**Purpose:** Perform automated code reviews and suggest refactors.

**Command Example:**
```
./agents/review.sh --path src/components --output suggestions.json
```

**Analysis Performed:**
- Detect dead code and unused imports.
- Identify large functions (> 80 lines) for extraction.
- Suggest modern APIs (e.g., replacing `var` with `let/const`).
- Provide a JSON report that can be fed into a PR comment bot.

---

## Integration with OpenCode

OpenCode provides a unified interface for running agents and handling their output. To invoke an agent from an OpenCode session, use the `task` tool with the appropriate `subagent_type` (e.g., `coder`). Example:
```json
{
  "command": "generate",
  "description": "Create a React component",
  "prompt": "./agents/generate.sh component Card --framework react",
  "subagent_type": "coder"
}
```

OpenCode will:
1. Run the agent in a sandboxed subprocess.
2. Capture stdout/stderr and surface them in the UI.
3. Auto‑stage any generated files if the agent returns a success status.
4. Optionally create a commit using the OpenCode git workflow.

---

## Running Agents Locally

All agents are executable shell scripts located under the `agents/` directory. They follow the convention:
- `#!/usr/bin/env bash`
- Exit codes are meaningful (see each agent section).
- Logging is sent to stderr; data output goes to stdout or files.

**Example workflow:**
```bash
# Scaffold a new service
./agents/generate.sh service UserService --lang ts

# Lint the entire codebase and auto‑fix where possible
./agents/lint.sh --fix

# Run the test suite with coverage
./agents/test.sh --coverage
```

---

## Configuration

Agents read configuration from a shared `agents.config.json` placed at the repository root. Example:
```json
{
  "lint": {
    "eslintConfig": ".eslintrc.js",
    "fix": true
  },
  "test": {
    "jestConfig": "jest.config.js",
    "watch": false
  },
  "ci": {
    "nodeVersion": "20",
    "cache": true
  }
}
```

Each agent merges its defaults with the values from this file, allowing project‑specific overrides without modifying the script code.

---

## Extending the Agent Suite

1. **Add a new script** under `agents/` with a descriptive name.
2. Follow the existing banner (usage, exit codes, env vars).
3. Add a corresponding entry in `agents.config.json` if custom settings are needed.
4. Update this `AGENTS.md` file – add a new section following the format used above.
5. Run `./agents/verify.sh` (provided) to ensure the new agent complies with the repository’s lint & test standards.

---

## Best Practices

- Keep scripts POSIX‑compatible where possible.
- Validate inputs early and emit helpful error messages.
- Use `set -euo pipefail` at the top of each script.
- Document environment variables that affect behaviour (e.g., `CI=true`).
- Write unit tests for complex Bash logic using `bats-core` (included as a dev dependency).
- Do not hard‑code absolute paths; rely on `$PWD` or relative paths.
- Prefer `npm exec` over globally installed binaries to ensure version consistency.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Agent exits with `127` | Missing dependency (e.g., `jq`) | Install via `npm i -D jq` or ensure it exists in `$PATH`. |
| No files generated by `generate.sh` | Template path mis‑configured | Verify `agents.config.json` `templatesPath` entry.
| Lint fails despite `--fix` | Files excluded from ESLint config | Add glob patterns to `.eslintignore`.
| CI workflow does not trigger | Missing `push` event in GitHub Actions | Run `./agents/ci.sh setup --provider github --update-workflow`.

For deeper issues, consult the agent’s `--help` output or inspect the script’s internal log statements (prefixed with `[DEBUG]`).

---

## Backend Structure

The backend is organized as a modular Python package:

```
backend/
├── __init__.py       # Package exports (models, state, config)
├── main.py           # FastAPI application entry point
├── config.py         # Configuration constants and paths (LOG_DIR, STATIC_DIR, etc.)
├── models.py         # Pydantic models (JobStatus, ComicJob, request DTOs)
├── state.py          # Global state (jobs, job_queue, active_websockets, models)
├── persistence.py    # Job save/load and image persistence (save_jobs, load_jobs)
├── broadcasting.py   # WebSocket and progress broadcasting functions
├── jobs.py           # Job processing worker (job_worker, process_job)
├── utils.py          # Helper utilities (log_system_resources, _image_to_base64, slug generation)
└── api/
    ├── __init__.py
    └── routes.py     # All API route handlers
```

**Entry Point:**
```bash
python -m backend.main
# or
uvicorn backend.main:app --host 0.0.0.0 --port 7860
```

---

## License

All agents are released under the same license as the main project (see `LICENSE` file). Modifications must retain the original copyright notices.
