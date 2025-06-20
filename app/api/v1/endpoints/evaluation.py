from fastapi import APIRouter
from app.api.v1.schemas import EssayEvaluationRequest, EvaluationResultItem
# evaluate_essay_with_graph 함수를 임포트
from app.services.evaluation_service import evaluate_essay_with_graph
from typing import List

router = APIRouter()

@router.post(
    "/essay-eval",
    response_model=List[EvaluationResultItem],
    summary="Evaluate an English Essay",
    description="Asynchronously evaluates an essay based on four rubric items: introduction, body, conclusion, and grammar.",
)
async def evaluate_essay_endpoint(request: EssayEvaluationRequest):
    # LangGraph 기반의 서비스 함수 호출
    results = await evaluate_essay_with_graph(request)
    return results