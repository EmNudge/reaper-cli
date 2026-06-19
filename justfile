default: check

install:
    uv sync

fmt:
    uv run ruff format .
    uv run ruff check --fix .

check:
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check src

test:
    uv run pytest -q

ci: check test
