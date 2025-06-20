# AI Essay Evaluation System

FastAPI 기반 에세이 자동 평가 API. LangGraph를 통해 평가 파이프라인의 제어 흐름을 관리하고, Azure OpenAI `gpt-4o-mini`를 LLM으로 사용.

---

## 실행 환경 구성



### Build & Run
1.  **Repository Clone**
    
    ```bash
    git clone https://github.com/Big-Shu-Nim/essay_eval
    cd essay_eval
    ```
    

2.  **Environment Variables**
    `.env.example`을 `.env`로 복제 후, 필요한 값을 채울 것.
    ```bash
    cp .env.example .env
    ```

3.  **Docker Compose**
    빌드 및 데몬 실행.
    ```bash
    docker compose up --build -d
    ```
    - API Docs: `http://localhost:8000/docs`
    - Shutdown: `docker compose down`

---


## API 사용 예시

API는 `http://localhost:8000/v1/essay-eval` 엔드포인트에 `POST` 요청을 보내는 방식으로 사용.

### 요청 (Request)

`curl`을 사용한 요청 예시는 다음과 같음.

```bash

curl -X 'POST' \
  'http://localhost:8000/v1/essay-eval' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "level_group": "intermediate",
  "topic_prompt": "Describe your dream vacation.",
  "submit_text": "I want to go to the beach. The weather is warm and I can swim in the sea. It will be a lot of fun because I like summer."
}'
```


### 아키텍처 및 설계 결정

LLM의 비결정성을 제어하고, 도메인 특화 규칙을 강제하기 위해 LangGraph 기반의 상태 머신(State Machine) 아키텍처를 채택.

### 1. Control Flow: LangGraph State Machine

-   **Motivation:**
    단순 Chaining 방식은 조건부 분기 및 동적 파이프라인 구성에 한계가 명확. 평가 프로세스의 각 단계를 독립된 노드로 정의하고, 상태(State) 전이를 통해 데이터 흐름을 명시적으로 제어할 필요성 대두.

-   **Implementation:**
    `langgraph.StateGraph`를 사용, 전체 워크플로우를 DAG(유향 비순환 그래프)로 모델링.
    -   **State:** `TypedDict`로 각 노드를 거치며 공유될 메모리 구조를 정의. (e.g., `word_count`, `has_core_issue` flag)
    -   **Nodes:** 각 노드는 `(State) -> dict` 시그니처를 따르는 비동기 함수. State의 일부만 반환하여 머지(merge)하는 방식으로 상태를 업데이트.
    -   **Edges:** `add_conditional_edges`를 사용, `preprocess` 노드의 출력값(`is_valid_language`)에 따라 워크플로우를 분기시키거나 종료. 병렬 실행이 필요한 구간은 더미 노드(fork)를 통해 두 개의 엣지로 분기.

-   **Workflow:**
    ```
    [Entry: preprocess] -> [Edge: Conditional] --(Valid)--> [Node: fork] -> [Nodes: evaluate_structure | evaluate_grammar]
                           |
                           +--(Invalid)--> [END]

    [Nodes: evaluate_structure, evaluate_grammar] -> [Node: synthesize] -> [END]
    ```

### 2. Pre-processing & Guardrails

-   **Motivation:**
    잘못된 입력으로 인한 불필요한 LLM 호출은 비용 및 Latency 낭비. API 진입점에서 예측 가능한 오류는 사전 차단이 필수.

-   **Implementation:**
    `preprocess` 노드에서 가드레일 로직을 수행.
    -   **Null/Empty Validation:** `level_group`, `submit_text`의 존재 여부를 체크. 실패 시 `HTTPException`을 발생시키는 대신, 그래프의 `error_message` 상태를 업데이트하고 `END`로 분기.
    -   **Language Validation:** 100% ASCII 체크 대신, `non-ascii` 문자의 비율이 임계값(10%)을 초과하는 경우에만 `invalid_language`로 처리. 텍스트의 전체 길이를 고려한 정규화된 검증 방식.

### 3. Post-processing & Dynamic Scoring

-   **Motivation:**
    LLM의 점수는 정성적 평가에 유용하나, 정량적 비즈니스 규칙(e.g., 최소 단어 수)을 일관되게 적용하지 못함. LLM의 평가와 결정론적 규칙을 결합하여 최종 점수를 보정할 필요.

-   **Implementation:**
    `synthesize` 노드에서 최종 점수를 재계산.
    1.  **Core Issue Penalty:**
        -   `evaluate_structure` 노드는 LLM의 `corrections` 결과에서 레벨별 핵심 키워드(e.g., "reason", "evidence")의 존재 여부를 분석, `has_core_issue` 플래그를 State에 기록.
        -   `synthesize` 노드는 이 플래그가 `True`일 경우, LLM이 부여한 점수에서 추가 감점을 적용.

    2.  **Word Count Penalty:**
        -   `preprocess`에서 계산된 `word_count`를 State를 통해 전달받음.
        -   `level_group`별로 정의된 최소 단어 수 기준에 미달 시, 점수를 차등 감점.

이러한 설계는 LLM을 단순 호출하는 것을 넘어, 제어 가능한 워크플로우 내에서 예측 가능한 결과를 생성하기 위한 결정

---


    ```
