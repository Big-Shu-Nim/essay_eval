# app/services/evaluation_service.py

import asyncio
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langsmith import traceable # LangSmith 추적을 위한 데코레이터
from app.api.v1.schemas import EssayEvaluationRequest, EvaluationResultItem
from app.services.llm_service import get_structured_evaluation

# Jinja2 템플릿 로더 설정 (변경 없음)
env = Environment(loader=FileSystemLoader("app/prompts/v1"), autoescape=select_autoescape())
template = env.get_template("rubric_evaluation.md")

RUBRIC_ITEMS = ["introduction", "body", "conclusion", "grammar"]

@traceable(run_type="chain", name="Rubric Item Evaluation") # "llm"에서 "chain"으로 변경하는 것이 더 정확합니다.
async def evaluate_single_rubric(request: EssayEvaluationRequest, rubric_item: str) -> EvaluationResultItem:
    """단일 루브릭 항목을 평가하는 비동기 함수"""
    system_prompt = template.render(
        level_group=request.level_group,
        rubric_item=rubric_item,
        topic_prompt=request.topic_prompt,
        submit_text=request.submit_text,
    )
    user_prompt = f"Please evaluate the provided essay for the '{rubric_item}' rubric item."
    
    # LangChain 호출은 자동으로 추적되므로, 수동 추적 코드가 필요 없습니다.
    llm_output = await get_structured_evaluation(system_prompt, user_prompt)

    return EvaluationResultItem(
        rubric_item=rubric_item,
        score=llm_output.score,
        corrections=llm_output.corrections,
        feedback=llm_output.feedback
    )


@traceable(run_type="chain", name="Essay Evaluation Pipeline")
async def evaluate_essay(request: EssayEvaluationRequest) -> list[EvaluationResultItem]:
    """에세이 평가의 전체 파이프라인을 비동기로 실행합니다."""
    tasks = [evaluate_single_rubric(request, item) for item in RUBRIC_ITEMS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results = []
    for result in results:
        if isinstance(result, Exception):
            print(f"An error occurred during evaluation: {result}")
        else:
            processed_results.append(result)

    return processed_results