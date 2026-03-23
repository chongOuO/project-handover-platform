"""LangGraph 節點 2：AI 生成 API 使用文件。

讀取 ``markdown_content`` 並構建精心設計的 Prompt，
呼叫 :class:`~app.infrastructure.adapters.llm_client.LLMClient`
讓 AI 模型分析原始碼報告並生成標準化的 API 使用文件 Markdown 文本。
"""

from __future__ import annotations

import logging

from app.application.graphs.state import GraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

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


async def generate_api_docs_node(state: GraphState) -> GraphState:
    """呼叫 LLM 分析原始碼內容並生成 API 使用文件。

    **邏輯重點**：此節點是 LLM 的第一次呼叫，專注於 API 介面描述。
    Prompt 採用結構化指令（章節指定 → 格式要求 → 範例補充），
    確保即使原始碼未明確定義完整 API，LLM 仍能輸出有意義的文件。

    Args:
        state: 需包含 ``markdown_content``（由前一節點填入）。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        新增了 ``api_docs_content`` 欄位。
    """
    logger.info("[generate_api_docs_node] 開始生成 API 使用文件...")

    prompt = _API_DOCS_PROMPT_TEMPLATE.format(
        markdown_content=state["markdown_content"]
    )
    api_docs = await _llm.complete(prompt)

    logger.info("[generate_api_docs_node] 完成，輸出長度：%d 字元", len(api_docs))
    return {"api_docs_content": api_docs}
