.PHONY: install test test-backend test-controller test-frontend test-integration test-real-groq smoke prepare-releases up down

install:
	python3.11 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	.venv/bin/python -m pip install -r lab-controller/requirements.txt
	cd frontend && npm install

test: test-backend test-frontend

test-backend:
	.venv/bin/python -m pytest backend/tests -q

test-controller:
	.venv/bin/python -m pytest backend/tests/test_lab_controller.py -q

test-frontend:
	cd frontend && npm test

smoke:
	docker compose config --quiet
	.venv/bin/python -m pytest backend/tests/test_workflow.py -q

test-integration:
	$(MAKE) test-real-groq

test-real-groq:
	@test "$$RUN_REAL_LAB" = "1" || (echo "Set RUN_REAL_LAB=1 and REAL_LAB_API_URL for a disposable running lab."; exit 1)
	.venv/bin/python -m pytest backend/tests/integration -q -m real_groq

prepare-releases:
	./scripts/build-lab-releases.sh

up:
	docker compose up --build

down:
	docker compose down
