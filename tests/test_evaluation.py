import pytest
from httpx import AsyncClient
from pytest_mock import MockerFixture

# 테스트에 필요한 모든 모델과 서비스 함수를 임포트합니다.
from app.api.v1.schemas import EssayEvaluationRequest, RubricEvaluationOutput, EvaluationResultItem, CorrectionDetail
from app.services import evaluation_service

# 모든 테스트를 비동기로 실행하도록 설정합니다.
pytestmark = pytest.mark.asyncio

# --- Fixtures: 테스트에 필요한 데이터와 모의 객체를 미리 만들어 둡니다. ---

@pytest.fixture
def valid_request() -> EssayEvaluationRequest:
    """테스트에 사용할 유효한 EssayEvaluationRequest 객체를 생성합니다."""
    return EssayEvaluationRequest(
        level_group="intermediate",
        topic_prompt="Describe your dream vacation.",
        submit_text="I want to go to the beach. It is a very good place."
    )

@pytest.fixture
def mock_llm_output() -> RubricEvaluationOutput:
    """_run_single_evaluation 내부의 LLM 호출이 반환할 모의 RubricEvaluationOutput 객체."""
    return RubricEvaluationOutput(
        score=2,
        corrections=[CorrectionDetail(highlight="I want to go", issue="A minor issue.", correction="I would like to go")],
        feedback="This is a mocked feedback."
    )

@pytest.fixture
def mock_evaluation_result_item(mock_llm_output: RubricEvaluationOutput) -> EvaluationResultItem:
    """_run_single_evaluation 함수가 반환할 모의 EvaluationResultItem 객체."""
    return EvaluationResultItem(
        rubric_item="introduction", # 기본값으로 introduction 설정
        score=mock_llm_output.score,
        corrections=mock_llm_output.corrections,
        feedback=mock_llm_output.feedback
    )

# --- Service Layer & LangGraph Node Tests ---

async def test_preprocess_node_success(valid_request: EssayEvaluationRequest):
    """LangGraph: preprocess_text 노드가 성공적으로 작동하는지 테스트합니다."""
    initial_state = {"request": valid_request}
    result_state = await evaluation_service.preprocess_text(initial_state)
    
    assert result_state["is_valid_language"] is True
    assert result_state["word_count"] > 0

@pytest.mark.parametrize("text, expected_msg, expected_type", [
    
      ("", "Submission text cannot be empty.", "validation_error"),
    ("이것은 한글입니다.", "Please write in English. Only English, numbers, and basic punctuation are allowed.", "invalid_language"),
])
async def test_preprocess_node_failures(text: str, expected_msg: str, expected_type: str):
    """LangGraph: preprocess_text 노드가 다양한 실패 케이스를 잘 처리하는지 테스트합니다."""
    request = EssayEvaluationRequest(level_group="basic", topic_prompt="t", submit_text=text)
    initial_state = {"request": request}
    result_state = await evaluation_service.preprocess_text(initial_state)
    
    assert result_state["is_valid_language"] is False
    assert result_state["error_message"] == expected_msg
    assert result_state["error_type"] == expected_type

async def test_evaluate_structure_node(mocker: MockerFixture, valid_request: EssayEvaluationRequest, mock_evaluation_result_item: EvaluationResultItem):
    """LangGraph: evaluate_structure_sequentially 노드가 올바르게 작동하는지 테스트합니다."""
    # _run_single_evaluation 함수를 모킹합니다. 이 함수는 EvaluationResultItem을 반환합니다.
    mocker.patch(
        "app.services.evaluation_service._run_single_evaluation", 
        return_value=mock_evaluation_result_item
    )
    # 키워드 분석 함수도 모킹합니다.
    mocker.patch(
        "app.services.evaluation_service.analyze_for_core_issue",
        return_value=False # 이 테스트에서는 핵심 이슈가 없다고 가정
    )
    
    initial_state = {"request": valid_request}
    result_state = await evaluation_service.evaluate_structure_sequentially(initial_state)
    
    assert "introduction_eval" in result_state
    assert result_state["introduction_eval"].rubric_item == "introduction"
    assert "body_eval" in result_state
    assert "conclusion_eval" in result_state
    assert result_state["intro_has_core_issue"] is False

async def test_post_evaluate_node_with_adjustments(mock_evaluation_result_item: EvaluationResultItem):
    """LangGraph: post_evaluate_and_synthesize 노드의 점수 조정 로직을 상세히 테스트합니다."""
    advanced_request = EssayEvaluationRequest(level_group="advanced", topic_prompt="t", submit_text="short text")
    
    # 시나리오: Advanced 레벨인데 글자 수가 부족하고, Body에는 핵심 이슈가 있었던 경우
    initial_state = {
        "request": advanced_request,
        "word_count": 50, # 150단어 미만으로 설정
        "introduction_eval": mock_evaluation_result_item.model_copy(update={"score": 2, "rubric_item": "introduction"}),
        "body_eval": mock_evaluation_result_item.model_copy(update={"score": 2, "rubric_item": "body"}),
        "conclusion_eval": mock_evaluation_result_item.model_copy(update={"score": 1, "rubric_item": "conclusion"}),
        "grammar_eval": mock_evaluation_result_item.model_copy(update={"score": 2, "rubric_item": "grammar"}),
        "intro_has_core_issue": False,
        "body_has_core_issue": True, # Body에 핵심 이슈가 있었다고 가정
        "conclusion_has_core_issue": False,
    }

    result_state = await evaluation_service.post_evaluate_and_synthesize(initial_state)
    final_results = result_state["final_results"]

    # 각 항목의 최종 점수 확인
    scores = {item.rubric_item: item.score for item in final_results}
    assert scores["introduction"] == 1 # 길이 페널티로 2점에서 1점으로 감점
    assert scores["body"] == 0         # 핵심 이슈(1점 감점) + 길이 페널티(1점 감점)로 2점에서 0점으로 감점
    assert scores["conclusion"] == 0   # 길이 페널티로 1점에서 0점으로 감점
    assert scores["grammar"] == 2      # 문법은 페널티 없음

# --- API Layer Tests ---

async def test_api_full_flow_success(client: AsyncClient, mocker: MockerFixture, mock_evaluation_result_item: EvaluationResultItem):
    """API 엔드포인트의 전체 성공 흐름을 테스트하여 커버리지를 높입니다."""
    # 서비스 로직의 가장 깊은 부분인 LLM 호출(_run_single_evaluation)만 모킹합니다.
    mocker.patch("app.services.evaluation_service._run_single_evaluation", return_value=mock_evaluation_result_item)
    # 키워드 분석도 모킹하여 예측 가능하게 만듭니다.
    mocker.patch("app.services.evaluation_service.analyze_for_core_issue", return_value=False)
    
    request_data = {"level_group": "Intermediate", "topic_prompt": "A topic", "submit_text": "A valid English text."}
    
    response = await client.post("/v1/essay-eval", json=request_data)
    
    assert response.status_code == 200
    response_json = response.json()
    assert len(response_json) == 4
    assert response_json[0]["score"] == 2 # 페널티가 없으므로 2점

async def test_api_invalid_language_error(client: AsyncClient):
    """API: 유효하지 않은 언어 입력 시 422 에러를 잘 처리하는지 테스트합니다."""
    request_data = {"level_group": "basic", "topic_prompt": "topic", "submit_text": "이것은 한글입니다."}
    response = await client.post("/v1/essay-eval", json=request_data)
    
    assert response.status_code == 422
    assert "Please write in English" in response.json()["detail"]

@pytest.mark.parametrize("key_to_remove", [
    "level_group",
    "submit_text",
    "topic_prompt",
])
async def test_api_missing_fields(client: AsyncClient, key_to_remove: str):
    """API: 필수 필드 누락 시 FastAPI가 422 에러를 잘 반환하는지 테스트합니다."""
    payload = {"level_group": "basic", "topic_prompt": "a topic", "submit_text": "a text"}
    del payload[key_to_remove]
    
    response = await client.post("/v1/essay-eval", json=payload)
    
    assert response.status_code == 422
    assert "Field required" in str(response.json())