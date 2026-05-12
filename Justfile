# Common project tasks. Run `just --list` to see them all.

default:
    @just --list

# Install/sync dependencies into the project virtualenv.
sync:
    uv sync

# Run the CLI through uv (pass extra args after `--`).
run *args:
    uv run street-viewer-360 {{args}}

# Lint with ruff.
lint:
    uv run ruff check .

# Auto-fix lint issues.
fix:
    uv run ruff check --fix .

# Format with ruff.
fmt:
    uv run ruff format .

# Run tests.
test:
    uv run pytest

# Run all pre-commit hooks.
pre-commit:
    uv run pre-commit run --all-files

# Generate a static package from sample data.
sample:
    uv run street-viewer-360 generate --input ./data/test-photos --output ./dist-output --overwrite
