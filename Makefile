.PHONY: install test test-backend test-frontend smoke up down

install:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

test: test-backend test-frontend

test-backend:
	.venv/bin/python -m pytest backend/tests -q

test-frontend:
	cd frontend && npm test

smoke:
	docker compose config --quiet
	.venv/bin/python -m pytest backend/tests/test_workflow.py -q

up:
	docker compose up --build

down:
	docker compose down
