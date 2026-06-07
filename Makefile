# Developer shortcuts. Thin wrappers over `uv` and the dev CLI (tools/normdev),
# which is NOT part of the shipped product (see tools/__init__.py).
# For arg-taking commands (e.g. `req show <ID>`, `smoke --keep`) call the dev CLI
# directly: `uv run python -m tools.normdev <subcommand> ...`.

.PHONY: sync test smoke req req-todo

sync:           ## create/refresh the venv and install (editable) + dev deps
	uv sync

test:           ## run the full test suite
	uv run pytest

smoke:          ## drive the real CLI end-to-end against a throwaway store
	uv run python -m tools.normdev smoke

req:            ## list all requirements (✓ = referenced by a test)
	uv run python -m tools.normdev req list

req-todo:       ## list only the requirements no test references yet
	uv run python -m tools.normdev req list --outstanding
