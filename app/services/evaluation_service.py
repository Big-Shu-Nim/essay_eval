# app/services/evaluation_service.py


import asyncio
import re
from typing import TypedDict, List, Optional

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from langgraph.graph import StateGraph, END

from app.api.v1.schemas import EssayEvaluationRequest, EvaluationResultItem, CorrectionDetail
from app.services.llm_service import get_structured_evaluation

# --- 1. LangGraph의 State 정의 ---
# 그래프의 각 단계를 거치며 데이터가 저장되고 업데이트될 '메모리'
class EvaluationState(TypedDict):
    request: EssayEvaluationRequest
    word_count: int
    is_valid_language: bool
    
    # 평가 결과
    introduction_eval: Optional[EvaluationResultItem]
    body_eval: Optional[EvaluationResultItem]
    conclusion_eval: Optional[EvaluationResultItem]
    grammar_eval: Optional[EvaluationResultItem]
    
    # --- 핵심 이슈 플래그 (새로 추가) ---
    # 각 평가가 끝난 후, 핵심 포인트 관련 이슈가 있었는지 여부를 저장
    intro_has_core_issue: bool
    body_has_core_issue: bool
    conclusion_has_core_issue: bool
    
    # 최종 결과
    final_results: Optional[List[EvaluationResultItem]]
    error_message: Optional[str]
    error_type: Optional[str]
    

# --- Jinja2 템플릿 로더 (기존과 동일) ---
env = Environment(loader=FileSystemLoader("app/prompts/v3"))
template = env.get_template("rubric_evaluation.md")

# --- 단일 평가 로직 (재사용을 위해 별도 함수로 분리) ---
async def _run_single_evaluation(
    request: EssayEvaluationRequest, 
    rubric_item: str,
    include_level_info: bool = True
) -> EvaluationResultItem:
    template_data = {
        "rubric_item": rubric_item,
        "topic_prompt": request.topic_prompt,
        "submit_text": request.submit_text,
    }
    if include_level_info:
        template_data["level_group"] = request.level_group
    else:
        template_data["level_group"] = "general (grammar focus)"

    system_prompt = template.render(**template_data)
    user_prompt = f"Please evaluate the provided essay for the '{rubric_item}' rubric item."
    
    llm_output = await get_structured_evaluation(system_prompt, user_prompt)

    return EvaluationResultItem(
        rubric_item=rubric_item,
        score=llm_output.score,
        corrections=llm_output.corrections,
        feedback=llm_output.feedback,
    )

# --- 2. LangGraph 노드(Node) 함수 정의 ---
# 각 노드는 state를 입력으로 받아 처리 후, 업데이트된 state의 일부를 반환

async def preprocess_text(state: EvaluationState) -> dict:
    """노드 1: 전처리 - 길이 및 언어 유효성 검사"""
    print("--- Executing Node: preprocess_text ---")
    request = state['request']
    text_to_check = request.submit_text
    
    word_count = len(text_to_check.split())
    
    # 텍스트가 비어있는 경우도 언어 오류로 처리
    if not text_to_check:
        return {
            "is_valid_language": False,
            "word_count": 0,
            "error_message": "Submission text cannot be empty.",
            "error_type": "validation_error" # 입력값 유효성 에러
        }
     # 영문 확인    
    allowed_chars_pattern = re.compile(r"^[a-zA-Z0-9\s.,!?'\"()’“”—\U0001F300-\U0001FADF]+$")
    
    if not text_to_check or not allowed_chars_pattern.match(text_to_check):
        return {
            "is_valid_language": False,
            "word_count": word_count,
            "error_message": "Please write in English. Only English, numbers, and basic punctuation are allowed.",
            "error_type": "invalid_language"
        }
    
    return {
        "is_valid_language": True,
        "word_count": word_count
    }


def analyze_for_core_issue(level: str, corrections: List[CorrectionDetail]) -> bool:
    """
    LLM의 correction 리스트(CorrectionDetail 객체들)를 분석하여
    핵심 포인트 관련 이슈가 있는지 판단하는 헬퍼 함수
    """
    if not corrections:
        return False  # 수정 사항이 없으면 핵심 이슈도 없음

    # 레벨별 핵심 포인트를 나타내는 키워드
    level_keywords = {
        # Basic: 내용 명확성 (내용이 불분명하거나, 너무 단순해서 이해가 안 되는 경우)
        "basic": ["unclear", "clarity", "confusing", "vague", "not specific", "hard to understand"],
        
        # Intermediate: 근거/전개 (이유나 예시가 부족하거나, 전개가 부자연스러운 경우)
        "intermediate": ["support", "reason", "example", "evidence", "development", "expand on", "not well-developed", "lacks detail"],
        
        # Advanced: 구조/논지 (글의 흐름, 문단 간의 연결, 논리의 일관성이 부족한 경우)
        "advanced": ["structure", "cohesion", "flow", "logical connection", "organization", "argument", "thesis"],
        
        # Expert: 논리/설득력 (주장이 설득력이 없거나, 미묘한 뉘앙스 표현에 실패한 경우)
        "expert": ["persuasive", "nuance", "rhetoric", "compelling", "convincing", "counter-argument", "one-sided"]
    }

    keywords_to_check = level_keywords.get(level, [])
    if not keywords_to_check:
        return False # 해당 레벨에 정의된 키워드가 없으면 검사하지 않음

    for correction_item in corrections:
        # Pydantic 객체의 'issue' 속성에 직접 접근
        issue_text = (correction_item.issue or "").lower()

        for keyword in keywords_to_check:
            if keyword in issue_text:
                print(f"--- Core issue found! Level: '{level}', Keyword: '{keyword}', Issue: '{issue_text}' ---")
                return True  # 핵심 키워드가 하나라도 발견되면 즉시 True를 반환

    return False # 모든 correction을 확인했지만 핵심 이슈 없음음


async def evaluate_structure_sequentially(state: EvaluationState) -> dict:
    """노드 2: 구조 평가 - 서론, 본론, 결론을 순차적으로 실행하고 핵심 이슈를 분석"""
    print("--- Executing Node: evaluate_structure_sequentially ---")
    request = state['request']
    level = request.level_group

    # 1. 순차 평가 실행
    introduction_eval = await _run_single_evaluation(request, "introduction")
    body_eval = await _run_single_evaluation(request, "body")
    conclusion_eval = await _run_single_evaluation(request, "conclusion")

    # 2. LLM 평가 결과를 바탕으로 핵심 이슈 분석
    intro_has_core_issue = analyze_for_core_issue(level, introduction_eval.corrections)
    body_has_core_issue = analyze_for_core_issue(level, body_eval.corrections)
    conclusion_has_core_issue = analyze_for_core_issue(level, conclusion_eval.corrections)

    # 3. 분석 결과를 State에 저장하여 다음 노드로 전달
    return {
        "introduction_eval": introduction_eval,
        "body_eval": body_eval,
        "conclusion_eval": conclusion_eval,
        "intro_has_core_issue": intro_has_core_issue,
        "body_has_core_issue": body_has_core_issue,
        "conclusion_has_core_issue": conclusion_has_core_issue
    }

async def evaluate_grammar_in_parallel(state: EvaluationState) -> dict:
    """노드 3: 문법 평가 - 다른 노드와 병렬로 실행"""
    print("--- Executing Node: evaluate_grammar_in_parallel ---")
    request = state['request']
    # 문법 평가는 level_group 정보가 덜 중요하므로 False로 설정 
    grammar_eval = await _run_single_evaluation(request, "grammar", include_level_info=False)
    return {"grammar_eval": grammar_eval}

async def post_evaluate_and_synthesize(state: EvaluationState) -> dict:
    """
    노드 4: 후처리 - 전달받은 '핵심 이슈' 플래그와 길이를 바탕으로 점수 가중치를 적용합니다.
    """
    print("--- Executing Node: post_evaluate_and_synthesize ---")
    
    # 평가 결과와 핵심 이슈 플래그를 State에서 가져옴
    eval_items = {
        "introduction": (state['introduction_eval'], state.get('intro_has_core_issue', False)),
        "body": (state['body_eval'], state.get('body_has_core_issue', False)),
        "conclusion": (state['conclusion_eval'], state.get('conclusion_has_core_issue', False)),
        "grammar": (state['grammar_eval'], False)  # 문법은 핵심 이슈 분석 대상이 아님
    }
    
    word_count = state['word_count']
    level_group = state['request'].level_group
    
    final_adjusted_results = []
    
    for rubric_item, (eval_result, has_core_issue) in eval_items.items():
        # 1. LLM이 부여한 초기 점수를 가져오기기
        current_score = eval_result.score
        
        # 2. 핵심 포인트 이슈에 대한 가중치를 적용
        #    핵심 이슈가 발견되었고, 현재 점수가 0점보다 높다면 1점을 감점
        #    (예: 2점 -> 1점, 1점 -> 0점)
        if has_core_issue and current_score > 0:
            current_score -= 1
            eval_result.feedback += f" (Note: Score adjusted down due to a core issue related to the '{level_group}' level's focus point.)"

        # 3. 길이 미달에 대한 추가 페널티를 적용
        #    'advanced' 또는 'expert' 레벨에서만 길이 페널티를 더 엄격하게 적용
        min_len_map = {"advanced": 150, "expert": 200}
        min_len_for_level = min_len_map.get(level_group, 0)
        
        # 구조/내용 평가에만 길이 페널티를 적용
        if rubric_item != "grammar" and word_count < min_len_for_level:
            # 현재 점수가 0점보다 높다면, 추가로 1점을 더 감점
            if current_score > 0:
                current_score -= 1
                eval_result.feedback += f" (Note: Score further adjusted as the essay is shorter than {min_len_for_level} words.)"
        
        # 최종 조정된 점수를 결과 객체에 반영
        eval_result.score = current_score
        final_adjusted_results.append(eval_result)
        
    return {"final_results": final_adjusted_results}

# --- 3. 조건부 엣지(Edge) 함수 정의 ---
def decide_to_continue_or_end(state: EvaluationState) -> str:
    """전처리 후 다음 단계로 갈지, 에러로 종료할지 결정"""
    print("--- Making Decision: decide_to_continue_or_end ---")
    if state.get("is_valid_language") is False:
        return "end_with_error"  # 이 이름은 add_conditional_edges에서 매핑됨
    return "continue_to_evaluation"

# --- 4. LangGraph 그래프 빌드 ---
workflow = StateGraph(EvaluationState)

# 노드 추가
workflow.add_node("preprocess", preprocess_text)
# 병렬 실행을 위한 분기점 역할을 할 더미(dummy) 노드 추가. 
workflow.add_node("fork_to_parallel_eval", lambda state: state) 
workflow.add_node("evaluate_structure", evaluate_structure_sequentially)
workflow.add_node("evaluate_grammar", evaluate_grammar_in_parallel)
workflow.add_node("synthesize", post_evaluate_and_synthesize)

# 엣지 연결
# 1. 그래프의 시작점 설정
workflow.set_entry_point("preprocess")

# 2. 전처리 후, 조건에 따라 분기
workflow.add_conditional_edges(
    "preprocess",
    decide_to_continue_or_end,
    {
        # 성공하면 -> 더미 노드로 이동
        "continue_to_evaluation": "fork_to_parallel_eval",
        # 에러가 있으면 -> 그래프 종료
        "end_with_error": END
    }
)

# 3. 더미 노드에서 두 평가 노드로 엣지를 각각 연결하여 병렬 실행
workflow.add_edge("fork_to_parallel_eval", "evaluate_structure")
workflow.add_edge("fork_to_parallel_eval", "evaluate_grammar")

# 4. 두 평가가 모두 끝나면, 결과를 종합하는 노드로 모임
workflow.add_edge("evaluate_structure", "synthesize")
workflow.add_edge("evaluate_grammar", "synthesize")

# 5. 종합이 끝나면, 그래프 최종 종료
workflow.add_edge("synthesize", END)


# 그래프 컴파일
app_graph = workflow.compile()



# --- 5. 최종 API 서비스 함수 (이 함수를 API 엔드포인트에서 호출) ---
async def evaluate_essay_with_graph(request: EssayEvaluationRequest) -> List[EvaluationResultItem]:
    """LangGraph로 컴파일된 평가 파이프라인을 실행하고, 에러 유형에 따라 다르게 처리합니다."""
    initial_state = {"request": request}
    
    try:
        # 그래프 실행
        final_state = await app_graph.ainvoke(initial_state)

        # 그래프 실행 후 에러 상태 확인
        if final_state.get("error_message"):
            error_type = final_state.get("error_type")
            error_message = final_state.get("error_message")

            if error_type == "invalid_language": # 언어관련 처리리
                raise HTTPException(status_code=422, detail=error_message)
            else:
                # 그 외 그래프 내부에서 정의된 다른 에러들
                raise HTTPException(status_code=400, detail=error_message)
            
        return final_state.get("final_results", [])

    except Exception as e:
        
        if isinstance(e, HTTPException):
            raise e # 이미 HTTPException이면 그대로 다시 던짐
        
        print(f"An unexpected error occurred...: {e}")
        raise HTTPException(status_code=500, detail="An internal server error...")