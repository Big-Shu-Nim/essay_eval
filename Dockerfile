# --- Stage 1: Base ---
# 모든 스테이지에서 공유할 기본 환경 설정
# Python 버전을 3.11.8로 정확히 명시
FROM python:3.11.8-slim as base

# 시스템 환경 변수 설정
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

# 작업 디렉토리 설정
WORKDIR /app

# Poetry 설치
RUN pip install poetry


# --- Stage 2: Builder ---
# 의존성을 설치하는 빌드 전용 스테이지
FROM base as builder

# pyproject.toml과 poetry.lock 파일만 먼저 복사하여 Docker 캐시를 활용
COPY pyproject.toml poetry.lock ./

# --only main: 개발용 의존성(pytest 등)은 제외하고, 프로덕션용 의존성만 설치
RUN poetry install --only main --no-root


# --- Stage 3: Tester ---
# 테스트를 실행하는 전용 스테이지
FROM builder as tester

# pyproject.toml을 다시 복사 
COPY pyproject.toml ./

# 이번에는 개발용 의존성까지 모두 설치
# --no-root: 프로젝트 자체를 editable 모드로 설치하지 않음
RUN poetry install --no-root

# 테스트에 필요한 전체 소스 코드 복사
COPY . .

# 테스트 실행! PYTHONPATH를 설정하여 모듈을 찾을 수 있도록 함
# 이 단계에서 테스트가 실패하면 Docker 빌드 전체가 실패
RUN PYTHONPATH=. poetry run pytest


# --- Stage 4: Final ---
# 모든 테스트를 통과한 후, 실제 서버를 실행하는 최종 스테이지
FROM base as final

# Builder 스테이지에서 설치한 프로덕션용 의존성만 복사
COPY --from=builder /app/.venv ./.venv

# 애플리케이션 코드 복사
COPY ./app ./app
COPY ./app/prompts ./app/prompts

# 서버 실행
# 가상 환경의 uvicorn을 직접 실행
CMD ["./.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]