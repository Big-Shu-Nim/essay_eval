import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Azure OpenAI Settings
    AZURE_OPENAI_ENDPOINT: str = "https://hmb-test.openai.azure.com/"
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"
    AZURE_OPENAI_DEPLOYMENT_NAME: str

    # LangSmith Settings
    # LangChain이 이 환경 변수들을 자동으로 인식합니다.
    LANGSMITH_TRACING: str = "true"  # LangSmith 추적 활성화
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com" # LangSmith API 엔드포인트
    LANGSMITH_API_KEY: str              # LangSmith API 키
    LANGSMITH_PROJECT: str  # LangSmith 프로젝트 이름

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

# 설정 객체 생성
settings = Settings()

