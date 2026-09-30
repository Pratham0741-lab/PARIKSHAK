.PHONY: build up down test seed report dev eval help

help:
	@echo "ISRO SIH26170 Operational Automation Targets:"
	@echo "  make build   - Build all multi-stage Docker images (standalone Next.js & FastAPI)"
	@echo "  make up      - Launch the complete containerized stack in background"
	@echo "  make down    - Stop and tear down container services"
	@echo "  make test    - Run the Python test suite"
	@echo "  make dev     - Run backend (:8000) and frontend (:8080) together for local development"
	@echo "  make eval    - Held-out evaluation: regenerate SIH26170_EVALUATION_REPORT.md"
	@echo "  make seed    - Initialize DB schema, synthetic burn-in parts & predictions"
	@echo "  make report  - Same as make eval (kept for compatibility)"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

test:
	python -m pytest -v

seed:
	python scripts/bootstrap.py --no-server

report:
	python scripts/generate_sih_report.py

dev:
	python scripts/dev.py

eval:
	python -m evaluation.run
