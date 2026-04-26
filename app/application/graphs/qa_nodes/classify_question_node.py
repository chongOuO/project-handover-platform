"""Q&A LangGraph 節點：問題分類與關鍵字提取。

此節點是 QA 管線的第一個節點，負責：
1. 判斷問題屬於哪種類型（架構、API、實作細節、設定、通用）。
2. 從問題中提取搜尋關鍵字，供 ``retrieve_context_node`` 使用。

設計決策：
    採用小型、聚焦的 LLM Prompt（< 200 Token 輸入），
    最大化分類速度並降低 RPM 消耗。
"""

from __future__ import annotations

import json
import logging

from app.application.graphs.qa_state import QAGraphState
from app.domain.entities.qa_models import QuestionType
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

_CLASSIFY_PROMPT = """\
你是一個程式碼問答系統的問題分類器。請分析使用者的問題，輸出 JSON 物件。

## 問題類型說明
- "architecture"：系統架構、模組分層、服務之間的關係、整體設計模式。
- "api_usage"：API 端點定義、Request/Response 格式、路由、HTTP Method。
- "implementation"：特定功能的實作邏輯、演算法、業務規則、函式細節。
- "config"：環境變數、設定檔、部署配置、連線字串。
- "general"：無法明確分類的一般性問題。

## 輸出格式（嚴格遵守，只輸出 JSON）
{{
  "question_type": "<類型>",
  "keywords": ["<關鍵字1>", "<關鍵字2>", ...]
}}

## 規則
- keywords 最多 8 個，選取最能定位相關程式碼檔案的詞彙。
- keywords 優先使用英文技術詞彙（例如 "auth", "router", "database"）。
- 只輸出 JSON，不要有任何前言或說明。

## 使用者問題
{question}
"""


async def classify_question_node(state: QAGraphState) -> QAGraphState:
    """分類問題類型並提取搜尋關鍵字。

    **邏輯重點**：
    - 呼叫 LLM 解析問題意圖，輸出嚴格 JSON 格式。
    - 若 LLM 回應無法解析為合法 JSON，降級為 ``QuestionType.GENERAL``
      並以問題中的詞彙作為關鍵字，確保管線不中斷。

    Args:
        state: 需包含 ``question`` 欄位。

    Returns:
        更新後的 :class:`~QAGraphState`，包含 ``question_type`` 與 ``search_keywords``。
    """
    question = state["question"]
    logger.info("[classify_question_node] 分類問題：%s", question[:100])

    try:
        prompt = _CLASSIFY_PROMPT.format(question=question)
        raw = await _llm.complete(prompt)

        # 移除可能的 markdown code fence
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        question_type = QuestionType(parsed.get("question_type", "general"))
        keywords: list[str] = parsed.get("keywords", [])[:8]

        logger.info(
            "[classify_question_node] 分類結果：type=%s，keywords=%s",
            question_type.value,
            keywords,
        )
        return {
            "question_type": question_type,
            "search_keywords": keywords,
        }

    except Exception as exc:
        logger.warning(
            "[classify_question_node] 分類失敗，降級為 GENERAL：%s",
            exc,
            exc_info=True,
        )
        # 降級策略：以問題前 50 字元的詞彙作為關鍵字
        fallback_keywords = [w for w in question.lower().split() if len(w) > 2][:8]
        return {
            "question_type": QuestionType.GENERAL,
            "search_keywords": fallback_keywords,
        }
