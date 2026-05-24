.PHONY: dev worker migrate test lint install install-browsers production-check monitor install-systemd

install:
	uv pip install -e ".[dev]"

install-browsers:
	python -m playwright install chromium

migrate:
	python -m media_automata.cli migrate

dev:
	uvicorn media_automata.api:app --host 0.0.0.0 --port 8080 --reload

worker:
	python -m media_automata.cli worker --loop

test:
	pytest

lint:
	ruff check .

production-check:
	python -m media_automata.cli production-check --recover-openwa

monitor:
	python -m media_automata.cli monitor-once

install-systemd:
	./deploy/systemd/install_user_units.sh
