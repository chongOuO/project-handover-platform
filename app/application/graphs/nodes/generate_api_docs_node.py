"""LangGraph 節點 2：AI 生成 API 使用文件。

讀取 ``markdown_content`` 並構建精心設計的 Prompt，
呼叫 :class:`~app.infrastructure.adapters.llm_client.LLMClient`
讓 AI 模型分析原始碼報告並生成標準化的 API 使用文件 Markdown 文本。

**Token Budget Gate**：在送入 LLM 之前，檢查 ``content_token_estimate``，
若超過 TPM 安全上限則執行緊急截斷，確保不觸發 API 限制。
"""

from __future__ import annotations

import logging

from app.application.graphs.state import GraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

#: TPM 安全上限（保障單一請求輸入上限，以容納兩次序列呼叫於 250k TPM 中）。
_TPM_SAFE_INPUT_LIMIT: int = 100_000

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

#: API 文件生成的系統 Prompt 模板。
_API_DOCS_PROMPT_TEMPLATE = """\
你是一位精通技術文件撰寫的資深工程師，請根據以下專案原始碼報告，生成一份完整、專業的 **API 使用文件**。

# 撰寫要求

1. 使用 Markdown 格式（繁體中文撰寫）。
2. 文件頂部需包含 `# API 使用文件` 一級標題。
3. 依以下章節架構撰寫：
   - **專案概述**：簡介此專案的核心功能與定位（2-3句）。
   - **Base URL**：推斷或列出 API 的基礎路徑（如 `http://localhost:8000/api/v1`）。
   - **認證機制**：說明是否需要 Token / API Key，若無則明確標注「無需認證」。
   - **API 端點列表**：以表格呈現所有端點（Method | Path | 說明）。
   - **端點詳細說明**：每個端點需包含：
     - 請求格式（Request Body / Params）
     - 回應格式（Response Body，含欄位說明）
     - 錯誤代碼對照表（status_code | error_code | 說明）
     - 完整的 `curl` 範例。
4. 若原始碼中找不到 API 定義，請根據推斷的功能生成範例章節，並標注「（推斷）」。

---

# 以下是待分析的專案原始碼報告：

{markdown_content}

---

請直接輸出完整的 Markdown 文件，不要包含任何前言或後記說明。
"""


def _estimate_tokens(text: str) -> int:
    """估算文字的 Token 數量。

    Args:
        text: 欲估算的文字。

    Returns:
        估算的 Token 數量。
    """
    return int(len(text) / _CHARS_PER_TOKEN)


def _emergency_truncate(content: str, token_limit: int) -> str:
    """緊急截斷內容至指定 Token 上限。

    Args:
        content: 原始 Markdown 內容。
        token_limit: 目標 Token 上限。

    Returns:
        截斷後的內容。
    """
    target_chars = int(token_limit * _CHARS_PER_TOKEN)
    truncated = content[:target_chars]
    truncated += "\n\n<!-- [Emergency Truncation] 內容已被緊急截斷以符合 TPM 限制 -->"
    return truncated


async def generate_api_docs_node(state: GraphState) -> GraphState:
    """呼叫 LLM 分析原始碼內容並生成 API 使用文件。

    **邏輯重點**：此節點是 LLM 的第一次呼叫，專注於 API 介面描述。

    **Token Budget Gate**：在組裝 Prompt 前，檢查 ``content_token_estimate``。
    若估算值超過 ``_TPM_SAFE_INPUT_LIMIT``（200k Token），對 ``markdown_content``
    執行緊急截斷，確保單次 API 呼叫不觸發 TPM 限制。

    Prompt 採用結構化指令（章節指定 → 格式要求 → 範例補充），
    確保即使原始碼未明確定義完整 API，LLM 仍能輸出有意義的文件。

    Args:
        state: 需包含 ``markdown_content``（由前一節點填入）。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        新增了 ``api_docs_content`` 欄位。
    """
    logger.info("[generate_api_docs_node] 開始生成 API 使用文件...")

    markdown_content = state["markdown_content"]
    token_estimate = state.get("content_token_estimate", _estimate_tokens(markdown_content))

    # Token Budget Gate：緊急截斷
    if token_estimate > _TPM_SAFE_INPUT_LIMIT:
        logger.warning(
            "[generate_api_docs_node] Token 估算 %d 超過安全上限 %d，執行緊急截斷。",
            token_estimate,
            _TPM_SAFE_INPUT_LIMIT,
        )
        markdown_content = _emergency_truncate(markdown_content, _TPM_SAFE_INPUT_LIMIT)
        logger.info(
            "[generate_api_docs_node] 緊急截斷後 Token 估算：%d",
            _estimate_tokens(markdown_content),
        )

    prompt = _API_DOCS_PROMPT_TEMPLATE.format(
        markdown_content=markdown_content
    )
    api_docs = await _llm.complete(prompt)

    logger.info("[generate_api_docs_node] 完成，輸出長度：%d 字元", len(api_docs))
    return {"api_docs_content": api_docs}
