"""Q&A LangGraph 管線的全局共享狀態定義。

``QAGraphState`` 是 QA 管線三個節點（classify → retrieve → generate）
之間傳遞資料的唯一容器，使用 ``TypedDict`` 定義以兼容 LangGraph 狀態管理機制。
"""

from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict

from app.domain.entities.qa_models import QuestionType


class QAGraphState(TypedDict, total=False):
    """Q&A LangGraph 管線的全局共享狀態。

    使用 ``total=False`` 使所有欄位均為可選，允許節點逐步填充狀態。

    Attributes:
        question: 使用者輸入的問題字串。
        project_files_json: 序列化後的 ProjectFile 列表（JSON 字串）。
        markdown_content: 完整的 Markdown 報告字串（Phase 1 產出）。
        map_reduce_summary: Map-Reduce 精煉摘要（大型專案才有值，None 代表未觸發）。
        question_type: ``classify_question_node`` 分類後的問題類型。
        search_keywords: ``classify_question_node`` 提取的關鍵字列表。
        context_snippets: ``retrieve_context_node`` 組裝的上下文字串。
        referenced_files: ``retrieve_context_node`` 選中的檔案路徑列表。
        context_token_count: 上下文的估算 Token 數量（供調試）。
        used_map_reduce_summary: 是否使用了 Map-Reduce 摘要作為上下文來源。
        answer: ``generate_answer_node`` 生成的答案 Markdown 字串。
        error: 任何節點拋出的錯誤訊息（供調試用）。
    """

    # ── 輸入欄位（由 QAService 填入，觸發前提供）──────────────────────────────
    question: str
    project_files_json: str
    markdown_content: str
    map_reduce_summary: Optional[str]

    # ── 中間狀態（由 classify_question_node 填入）─────────────────────────────
    question_type: QuestionType
    search_keywords: List[str]

    # ── 中間狀態（由 retrieve_context_node 填入）──────────────────────────────
    context_snippets: str
    referenced_files: List[str]
    context_token_count: int
    used_map_reduce_summary: bool

    # ── 輸出欄位（由 generate_answer_node 填入）───────────────────────────────
    answer: str

    # ── 錯誤欄位（任何節點均可寫入）──────────────────────────────────────────
    error: Optional[str]
