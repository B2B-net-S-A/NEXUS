.PHONY: dev build migrate seed logs stop clean

# ─── Development ──────────────────────────────────────────────────────────────

dev:
	@echo "Starting DynaMinds ATS in development mode..."
	@cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
	@cd frontend && npm run dev

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# ─── Docker ───────────────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose up -d

stop:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

seed:
	docker compose exec backend python seed.py

# ─── Database / Migrations ────────────────────────────────────────────────────

migrate:
	@echo "Running Alembic migrations..."
	cd backend && alembic upgrade head

migrate-create:
	@read -p "Migration name: " name; \
	cd backend && alembic revision --autogenerate -m "$$name"

migrate-down:
	cd backend && alembic downgrade -1

migrate-history:
	cd backend && alembic history

# ─── Install ──────────────────────────────────────────────────────────────────

install-backend:
	cd backend && pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

install: install-backend install-frontend

# ─── Quality ──────────────────────────────────────────────────────────────────

lint-backend:
	cd backend && python -m flake8 app/

type-check-frontend:
	cd frontend && npm run type-check

lint-frontend:
	cd frontend && npm run lint

# ─── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	docker-compose down -v
	find backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find backend -name "*.pyc" -delete 2>/dev/null || true
