# tests/conftest.py


import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport

from app.main import app

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    FastAPI 앱과 함께 비동기 테스트를 수행하기 위한 HTTP 클라이언트 Fixture.
    ASGITransport를 사용하여 앱을 직접 transport 계층에 연결합니다.
    """
    # ASGITransport는 FastAPI 앱(ASGI 호환)을 httpx가 직접 요청을 보낼 수 있도록 해줍니다.
    transport = ASGITransport(app=app)
    
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c