# Contributing

Thank you for improving this project. The goal is to keep changes focused, safe for a **public** git remote, and easy to verify **locally**.

## Security and privacy

- **Never commit** `.env`, `data/`, `tokens/`, database files, or API keys. Use `.env.example` for new variables (empty or placeholder values only).
- Before a push, skim `git diff` for accidental paths (home directory, employer-specific URLs, real tokens).
- If a secret was ever committed, **rotate** that credential and history-clean if required (outside the scope of this doc).

## Signed commits (DCO-style)

We use **`git commit -s`** so each commit includes a `Signed-off-by` trailer (Developer Certificate of Origin style).

```bash
git commit -s -m "Short imperative subject"
```

Use your real name and a reachable email (set `user.name` / `user.email` in git config). If an automated tool appends unwanted trailers to messages, amend from a plain terminal or rebuild the commit with `git commit-tree` so only the intended subject and sign-off remain.

## Local testing

### Assistant (recommended first check)

1. Ollama running with models referenced in `.env`.
2. From the repo root:

   ```bash
   python -m src.app --transport cli
   ```

3. Exercise flows you changed: chat, `/help`, tool-related commands, reminders, etc.

### Discord / Telegram

- Run the matching `--transport` with valid tokens.
- Confirm behavior in a private test server/channel before relying on production settings.

### Speech

- Voice paths depend on `faster-whisper` and `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE`. On Apple Silicon, `mps` is typical; on NVIDIA, `cuda`.

### Optional services

- **Travel:** set `TRAVELPAYOUTS_TOKEN` locally to validate flight search.
- **Google:** place OAuth client JSON under `tokens/` as documented in `.env.example`.

## Tests and coverage

**Today there is no enforced per-function coverage gate in CI.** Ad hoc scripts named `test_*.py` may exist locally for experiments; they are not part of the default distribution policy for this repo.

**Expectations for contributors:**

- When you add or fix **non-trivial logic**, add or extend **automated tests** if the project introduces a runner (e.g. `pytest`) in tree, or document **manual steps** in your PR so reviewers can reproduce results.
- Aim to cover **new branches and edge cases** (empty API responses, missing tokens, malformed user input) near the code you touch.
- If you introduce `pytest`, prefer **small, fast** unit tests for pure functions; use integration tests sparingly and gate them behind env flags if they need Ollama or the network.

(If the maintainers add `pytest` + `pytest-cov`, run `pytest --cov=src` before opening a PR and note coverage for new modules in the PR description.)

## Code style

- **Python 3.11+** typing and idioms consistent with the existing code.
- Optional dev tools from `pyproject.toml`:

  ```bash
  pip install -e ".[dev]"
  ruff check .
  ruff format .
  ```

- Match surrounding style: imports, naming, and error handling patterns in the files you edit.

## Pull requests

- One logical change per PR when possible.
- Describe **what** changed and **why** in plain language.
- List **how you tested** (CLI commands, transports, manual scenarios).
- Do not add new markdown files unless they are part of the change and agreed with maintainers.

## Questions

Open an issue or discuss in your team channel; keep issue text free of secrets and private data.
