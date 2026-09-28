.PHONY: build up down test seed report help

help:
	@echo "ISRO SIH26170 Operational Automation Targets:"
	@echo "  make build   - Build all multi-stage Docker images (standalone Next.js & FastAPI)"
	@echo "  make up      - Launch the complete containerized stack in background"
	@echo "  make down    - Stop and tear down container services"
	@echo "  make test    - Run complete automated test suite (32 unit, API & E2E tests)"
	@echo "  make seed    - Initialize DB schema, synthetic burn-in parts & predictions"
	@echo "  make report  - Generate official competition evaluation report & Rich tables"

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
