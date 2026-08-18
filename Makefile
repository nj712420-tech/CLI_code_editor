.PHONY: install dev lint format type test run

install:
	pip install -e ".[dev]"

lint:
	ruff check aide tests

format:
	ruff format aide tests
	ruff check --fix aide tests

type:
	mypy aide

test:
	pytest

dev:
	textual run --dev aide.tui.app:AideApp