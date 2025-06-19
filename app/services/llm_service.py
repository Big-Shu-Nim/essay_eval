# app/services/llm_service.py

from langchain_openai import AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.api.v1.schemas import RubricEvaluationOutput

# 1. LangChain의 AzureChatOpenAI 클라이언트 초기화
# LangSmith 환경 변수가 설정되어 있으면 자동으로 모든 호출이 추적됩니다.
llm = AzureChatOpenAI(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    temperature=0.1,
    max_retries=2,
)

# 2. 구조화된 출력을 위한 LLM 체인 생성
# .with_structured_output() 메서드는 내부적으로 response_format을 사용합니다.
# 2024-12-01-preview 버전에서는 이 기능이 지원됩니다.
structured_llm = llm.with_structured_output(RubricEvaluationOutput)

# 3. 프롬프트와 LLM을 연결하는 전체 체인을 미리 정의
# 이렇게 하면 호출 코드가 더 간결해집니다.
chain = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    ("user", "{user_prompt}")
]) | structured_llm

async def get_structured_evaluation(system_prompt: str, user_prompt: str) -> RubricEvaluationOutput:
    """
    LangChain을 사용하여 LLM을 비동기적으로 호출하고 구조화된 평가 결과를 받습니다.
    """
    try:
        # 미리 정의된 체인을 비동기적으로 실행합니다.
        response = await chain.ainvoke({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        })
        return response
    except Exception as e:
        print(f"Error calling LangChain chain: {e}")
        raise