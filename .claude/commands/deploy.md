# /deploy — 빌드 검증 + Git 커밋 + Push

코드 변경사항을 검증하고 GitHub에 push합니다.

## 절차

1. **백엔드 검증**: `cd backend && uv run python -c "from app.main import app; print('OK')"`
2. **프론트엔드 빌드**: `cd frontend && npx next build` — 에러 없는지
3. **변경 파일 확인**: `git status` + `git diff --stat`
4. **커밋**: 변경 내용을 의미 단위로 커밋 (Co-Authored-By 포함)
5. **Push**: GitHub token은 사용자에게 요청하여 1회성으로 사용, push 후 remote URL에서 제거

## 규칙
- 빌드 실패 시 push 하지 마세요
- `.env`, `data/` 가 push 되지 않는지 확인하세요
- 커밋 메시지는 영어로, 변경 내용을 명확하게
