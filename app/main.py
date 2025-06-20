# app/main.py

from fastapi import FastAPI
from app.api.v1.endpoints import evaluation
from app.core.config import settings
# LangSmith 설정을 자동으로 로드하기 위해 settings를 임포트
_ = settings

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(
    title="Essay Evaluation API",
    description="An API to evaluate student essays using AI.",
    version="1.0.0"
)

# /v1 경로 아래에 evaluation 라우터를 포함시킴
# 이렇게 하면 /v1/essay-eval 경로가 활성화
app.include_router(evaluation.router, prefix="/v1", tags=["Evaluation"])

@app.get("/", tags=["Root"])
def read_root():
    """
    API 서버가 정상적으로 실행 중인지 확인하는 기본 엔드포인트
    """
    return {"message": "Welcome to the Essay Evaluation API!"}