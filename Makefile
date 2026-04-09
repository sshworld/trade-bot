.PHONY: setup dev start backend frontend seed lint test db

# 처음 한 번만 실행
setup:
	bash scripts/setup.sh

# Docker Compose로 전부 시작 (DB + Backend + Frontend)
dev:
	docker compose up

# DB 없이 백엔드 + 프론트엔드 동시 실행 (간편 모드)
start:
	@echo "Starting backend + frontend..."
	@cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 & \
	cd frontend && pnpm dev & \
	wait

# 개별 실행
db:
	docker compose up db -d

backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && pnpm dev

# 히스토리컬 데이터 시드
seed:
	cd backend && uv run python -m scripts.seed_data

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

test:
	cd backend && uv run pytest
	cd frontend && pnpm test
