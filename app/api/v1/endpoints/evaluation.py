from fastapi import APIRouter, HTTPException, status
from app.api.v1.schemas import EssayEvaluationRequest, EvaluationResultItem
from app.services import evaluation_service
from typing import List

router = APIRouter()

@router.post(
    "/essay-eval",
    response_model=List[EvaluationResultItem],
    summary="Evaluate an English Essay",
    description="Asynchronously evaluates an essay based on four rubric items: introduction, body, conclusion, and grammar.",
)
async def evaluate_essay_endpoint(request: EssayEvaluationRequest):
    """
    학생의 에세이 제출물을 받아 비동기적으로 평가하고 결과를 반환합니다.

    - **level_group**: 평가 목표 기준 (Basic, Intermediate, Advanced, Expert)
    - **topic_prompt**: 에세이 주제
    - **submit_text**: 학생이 제출한 에세이
    """
    try:
        results = await evaluation_service.evaluate_essay(request)
        return results
    except Exception as e:
        # 서비스 로직에서 처리되지 않은 예외 처리
        print(f"Unhandled exception in evaluation endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during the evaluation process.",
        )