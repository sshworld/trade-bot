.PHONY: setup dev start backend seed lint test db

# 처음 한 번만 실행
setup:
	bash scripts/setup.sh

# Docker Compose로 전부 시작 (DB + Backend)
dev:
	docker compose up

# DB 없이 백엔드 실행 (간편 모드)
start: backend

# 개별 실행
db:
	docker compose up db -d

backend:
	cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 히스토리컬 데이터 시드
seed:
	cd backend && uv run python -m scripts.seed_data

lint:
	cd backend && uv run ruff check .

test:
	cd backend && uv run pytest
