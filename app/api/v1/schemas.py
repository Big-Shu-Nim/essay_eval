from pydantic import BaseModel, Field, field_validator
from typing import List

# --- Request Schemas ---
class EssayEvaluationRequest(BaseModel):
    level_group: str = Field(..., examples=["Intermediate"], description="평가 목표 기준 레벨 (Basic, Intermediate, Advanced, Expert)")
    topic_prompt: str = Field(..., examples=["Describe your dream vacation."], description="에세이 주제")
    submit_text: str = Field(..., examples=["I want to go to..."], description="학생이 제출한 에세이 원문")

    # Pydantic v2의 field_validator를 사용하여 입력값을 변환/검증
    @field_validator('level_group')
    @classmethod
    def normalize_level_group(cls, v: str) -> str:
        """level_group 값을 소문자로 변환하여 정규화합니다."""
        if not v:
            raise ValueError("level_group cannot be empty.")
        return v.lower()

# --- Response Schemas ---
class CorrectionDetail(BaseModel):
    highlight: str = Field(..., description="문제가 되는 원문 문장 또는 구절")
    issue: str = Field(..., description="문제점에 대한 요약 (e.g., 'missing to-be')")
    correction: str = Field(..., description="개선된 문장")

class EvaluationResultItem(BaseModel):
    rubric_item: str = Field(..., examples=["introduction", "grammar"], description="평가 항목")
    score: int = Field(..., ge=0, le=2, description="항목별 점수 (0, 1, 2)")
    corrections: List[CorrectionDetail] = Field(..., description="수정이 필요한 부분들")
    feedback: str = Field(..., description="항목에 대한 전반적인 피드백")

# --- LLM Tool Output Schema ---
# LLM이 JSON을 안정적으로 생성하도록 Pydantic 모델을 Tool로 사용
class RubricEvaluationOutput(BaseModel):
    """An evaluation for a single rubric item of an essay."""
    score: int = Field(..., ge=0, le=2, description="The score for this rubric item, from 0 to 2.")
    corrections: List[CorrectionDetail] = Field(..., description="A list of corrections for the essay text based on this rubric item.")
    feedback: str = Field(..., description="Overall feedback for this rubric item.")