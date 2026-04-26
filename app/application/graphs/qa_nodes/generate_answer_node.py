"""Q&A LangGraph 節點：答案生成。

此節點是 QA 管線的最終節點，負責：
1. 組裝完整的 Prompt（System Prompt + 上下文 + 問題）。
2. 呼叫 LLM 生成答案。
3. 設置 Token Budget Gate：確保最終 Prompt 不超過硬上限。

設計決策：
    答案要求 LLM 以 Markdown 格式回覆，引用具體檔案與行號，
    並在回答不確定的資訊時明確說明。
"""

from __future__ import annotations

import logging

from app.application.graphs.qa_state import QAGraphState
from app.domain.entities.qa_models import QuestionType
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

#: 最終送入 LLM 的 Prompt Token 硬上限（含 System Prompt + 上下文 + 問題）。
PROMPT_TOKEN_HARD_LIMIT: int = 800_000  # Gemini 2.5 Flash 1M ctx window 的 80%

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5


def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


_SYSTEM_PROMPT = """\
你是一個專業的程式碼問答助手，專門分析軟體專案並回答開發者的問題。

## 回答規範
1. 答案必須基於下方提供的「專案上下文」，引用具體的檔案路徑與代碼內容。
2. 若上下文中有相關資訊，直接引用並說明。
3. 若上下文中沒有足夠資訊，明確告知「根據現有上下文無法確定」，不要臆測。
4. 使用 Markdown 格式回答，適當使用代碼區塊、列表、標題。
5. 回答語言與問題語言一致（中文問題用中文回答，英文問題用英文回答）。

## 問題類型：{question_type}
"""

_USER_PROMPT_TEMPLATE = """\
## 專案上下文

{context_snippets}

---

## 使用者問題

{question}

請根據以上專案上下文回答問題。
"""


async def generate_answer_node(state: QAGraphState) -> QAGraphState:
    """呼叫 LLM 生成最終答案。

    **Token Budget Gate**：組裝前先估算總 Token 量，
    若超過 ``PROMPT_TOKEN_HARD_LIMIT``，對 ``context_snippets`` 進行尾部截斷。
    此為最後一道防線，正常情況下 ``retrieve_context_node`` 已控制在 60K 以內。

    **容錯設計**：LLM 呼叫失敗時，以結構化錯誤訊息回傳，
    並在 State 中設置 ``error`` 欄位，上層 Service 可據此判斷是否重試。

    Args:
        state: 需包含 ``question``、``context_snippets``、``question_type``。

    Returns:
        更新後的 :class:`~QAGraphState`，包含 ``answer``（和可能的 ``error``）。
    """
    question = state.get("question", "")
    context_snippets = state.get("context_snippets", "")
    question_type: QuestionType = state.get("question_type", QuestionType.GENERAL)

    logger.info(
        "[generate_answer_node] 開始生成答案。type=%s，context=%d token。",
        question_type.value,
        state.get("context_token_count", 0),
    )

    # ── Token Budget Gate ────────────────────────────────────────────────────
    system_prompt = _SYSTEM_PROMPT.format(question_type=question_type.value)
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        context_snippets=context_snippets,
        question=question,
    )
    full_prompt = system_prompt + "\n\n" + user_prompt
    total_tokens = _estimate_tokens(full_prompt)

    if total_tokens > PROMPT_TOKEN_HARD_LIMIT:
        # 截斷 context_snippets 尾部
        budget_chars = int(
            (PROMPT_TOKEN_HARD_LIMIT - _estimate_tokens(system_prompt) - _estimate_tokens(question) - 2000)
            * _CHARS_PER_TOKEN
        )
        context_snippets = context_snippets[:budget_chars] + "\n\n...[上下文因 Token 預算截斷]"
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            context_snippets=context_snippets,
            question=question,
        )
        full_prompt = system_prompt + "\n\n" + user_prompt
        logger.warning(
            "[generate_answer_node] 觸發 Token Budget Gate，上下文已截斷至 %d chars。",
            budget_chars,
        )

    # ── LLM 呼叫 ────────────────────────────────────────────────────────────
    try:
        answer = await _llm.complete(full_prompt)
        logger.info(
            "[generate_answer_node] 答案生成完成，%d 字元。",
            len(answer),
        )
        return {"answer": answer}

    except Exception as exc:
        error_msg = f"LLM 呼叫失敗：{exc}"
        logger.error(
            "[generate_answer_node] %s",
            error_msg,
            exc_info=True,
        )
        return {
            "answer": "抱歉，生成答案時發生錯誤，請稍後再試。",
            "error": error_msg,
        }
