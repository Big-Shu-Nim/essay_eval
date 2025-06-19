# tests/test_evaluation.py

import pytest
import asyncio
from httpx import AsyncClient
from pytest_mock import MockerFixture

# 테스트에 필요한 스키마와 서비스 함수를 임포트
from app.api.v1.schemas import EssayEvaluationRequest, RubricEvaluationOutput, CorrectionDetail, EvaluationResultItem
from app.services import evaluation_service

# 모든 테스트를 비동기로 실행하도록 마킹
pytestmark = pytest.mark.asyncio

# --- Fixtures: 테스트 데이터 및 모의 객체 설정 ---

@pytest.fixture
def valid_request_data() -> dict:
    """테스트에 사용할 유효한 API 요청 데이터"""
    return {
        "level_group": "Intermediate",
        "topic_prompt": "Describe your dream vacation.",
        "submit_text": "I want to go to the beach. It is very fun and I can swim."
    }

@pytest.fixture
def mock_llm_output() -> RubricEvaluationOutput:
    """LLM 서비스가 반환할 성공적인 모의(mock) 응답 객체"""
    return RubricEvaluationOutput(
        score=2,
        corrections=[
            CorrectionDetail(highlight="I want to go", issue="Good sentence", correction="I want to go")
        ],
        feedback="This is a mocked feedback. Great job!"
    )

@pytest.fixture
def mock_evaluation_result_item(mock_llm_output: RubricEvaluationOutput) -> EvaluationResultItem:
    """evaluate_single_rubric 함수가 반환할 모의 결과 아이템"""
    return EvaluationResultItem(
        rubric_item="introduction",
        score=mock_llm_output.score,
        corrections=mock_llm_output.corrections,
        feedback=mock_llm_output.feedback
    )

# --- Service Layer Tests: evaluation_service.py 테스트 ---

async def test_evaluate_single_rubric_service(mocker: MockerFixture, mock_llm_output: RubricEvaluationOutput):
    """
    'evaluate_single_rubric' 서비스 함수 단위 테스트
    """
    # LLM 호출 함수를 모킹
    mock_get_structured_eval = mocker.patch(
        'app.services.evaluation_service.get_structured_evaluation',
        return_value=mock_llm_output
    )
    
    request = EssayEvaluationRequest(
        level_group="Basic",
        topic_prompt="Test topic",
        submit_text="Test submission."
    )
    
    result = await evaluation_service.evaluate_single_rubric(request, "grammar")
    
    # 결과 검증
    assert isinstance(result, EvaluationResultItem)
    assert result.rubric_item == "grammar"
    assert result.score == mock_llm_output.score
    assert result.feedback == mock_llm_output.feedback
    
    # LLM 호출 함수가 올바른 인자와 함께 호출되었는지 확인
    mock_get_structured_eval.assert_awaited_once()

async def test_evaluate_essay_service_all_success(
    mocker: MockerFixture,
    mock_evaluation_result_item: EvaluationResultItem
):
    """
    'evaluate_essay' 서비스 함수가 모든 항목을 성공적으로 평가하는 경우 테스트
    """
    # evaluate_single_rubric 함수 자체를 모킹하여 병렬 처리 로직에 집중
    mock_single_rubric_eval = mocker.patch(
        'app.services.evaluation_service.evaluate_single_rubric',
        return_value=mock_evaluation_result_item
    )
    
    request = EssayEvaluationRequest.model_validate({
        "level_group": "Advanced",
        "topic_prompt": "Test",
        "submit_text": "This is a test essay for coverage."
    })
    
    results = await evaluation_service.evaluate_essay(request)
    
    # 결과 검증
    assert len(results) == 4  # 4개의 루브릭 항목
    assert all(isinstance(res, EvaluationResultItem) for res in results)
    assert mock_single_rubric_eval.await_count == 4 # 4번 호출되었는지 확인

async def test_evaluate_essay_service_partial_failure(
    mocker: MockerFixture,
    mock_evaluation_result_item: EvaluationResultItem
):
    """
    'evaluate_essay' 서비스 함수에서 일부 항목 평가가 실패하는 경우 테스트
    - asyncio.gather의 return_exceptions=True 로직을 커버하기 위함
    """
    # 2번은 성공, 2번은 실패하도록 side_effect 설정
    mock_single_rubric_eval = mocker.patch(
        'app.services.evaluation_service.evaluate_single_rubric',
        side_effect=[
            mock_evaluation_result_item,
            Exception("LLM Timeout for Body"),
            mock_evaluation_result_item,
            Exception("LLM Error for Grammar")
        ]
    )
    
    request = EssayEvaluationRequest.parse_obj({
        "level_group": "Expert",
        "topic_prompt": "Test",
        "submit_text": "This is another test essay."
    })
    
    results = await evaluation_service.evaluate_essay(request)
    
    # 결과 검증
    assert len(results) == 2  # 성공한 2개의 결과만 리스트에 포함됨
    assert all(isinstance(res, EvaluationResultItem) for res in results)
    assert mock_single_rubric_eval.await_count == 4

# --- API Layer Tests: evaluation.py 엔드포인트 테스트 ---

async def test_api_evaluate_essay_success(
    client: AsyncClient,
    mocker: MockerFixture,
    valid_request_data: dict,
    mock_evaluation_result_item: EvaluationResultItem
):
    """
    API 엔드포인트 성공 케이스 (/v1/essay-eval)
    """
    # 서비스 레이어를 모킹하여 API 레이어의 동작에만 집중
    mocker.patch(
        'app.services.evaluation_service.evaluate_essay',
        return_value=[mock_evaluation_result_item] * 4
    )
    
    response = await client.post("/v1/essay-eval", json=valid_request_data)
    
    assert response.status_code == 200
    response_json = response.json()
    assert isinstance(response_json, list)
    assert len(response_json) == 4
    assert response_json[0]['rubric_item'] == 'introduction'
    assert response_json[0]['score'] == 2

async def test_api_evaluate_essay_service_exception(
    client: AsyncClient,
    mocker: MockerFixture,
    valid_request_data: dict
):
    """
    API 호출 시 서비스 레이어에서 처리되지 않은 예외가 발생하는 경우
    """
    mocker.patch(
        'app.services.evaluation_service.evaluate_essay',
        side_effect=Exception("A critical service error occurred")
    )
    
    response = await client.post("/v1/essay-eval", json=valid_request_data)
    
    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred during the evaluation process."}

@pytest.mark.parametrize("invalid_payload, expected_detail_part", [
    (
        {"topic_prompt": "A", "submit_text": "B"}, # level_group 누락
        "'level_group' is a required field"
    ),
    (
        {"level_group": "Basic", "submit_text": "B"}, # topic_prompt 누락
        "'topic_prompt' is a required field"
    ),
    (
        {"level_group": "Basic", "topic_prompt": "A"}, # submit_text 누락
        "'submit_text' is a required field"
    ),
    (
        {"level_group": 123, "topic_prompt": "A", "submit_text": "B"}, # 잘못된 타입
        "Input should be a valid string"
    )
])
async def test_api_invalid_payload(
    client: AsyncClient,
    invalid_payload: dict,
    expected_detail_part: str
):
    """
    잘못된 요청 페이로드에 대해 422 에러를 반환하는지 파라미터화 테스트
    """
    response = await client.post("/v1/essay-eval", json=invalid_payload)
    
    assert response.status_code == 422
    # 에러 메시지에 특정 문자열이 포함되어 있는지 확인하여 더 정확한 테스트
    assert expected_detail_part in str(response.json())