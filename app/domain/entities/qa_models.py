"""Q&A 系統的 Domain 層實體定義。

此模組定義問答系統所用的 Pydantic 模型與列舉，
供 API Schema、Application Service 與 LangGraph 節點共同使用。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """問題類型分類。

    供 ``classify_question_node`` 輸出，影響 ``retrieve_context_node``
    的檔案優先權加權策略。

    Attributes:
        ARCHITECTURE: 架構、模組分層、服務互動等全域設計問題。
        API_USAGE: API 端點、Request/Response 格式、路由等問題。
        IMPLEMENTATION: 特定功能邏輯、演算法、業務規則等細節問題。
        CONFIG: 環境變數、設定檔、部署配置等問題。
        GENERAL: 無法明確分類，使用通用策略。
    """

    ARCHITECTURE = "architecture"
    API_USAGE = "api_usage"
    IMPLEMENTATION = "implementation"
    CONFIG = "config"
    GENERAL = "general"


class QAResult(BaseModel):
    """單次問答的結果實體。

    Attributes:
        answer: LLM 生成的答案 Markdown 字串。
        question_type: 分類後的問題類型。
        referenced_files: 本次回答所參考的檔案路徑列表。
        context_token_count: 本次送入 LLM 的上下文 Token 估算數量。
        used_map_reduce_summary: 是否使用了 Map-Reduce 摘要作為上下文來源。
    """

    answer: str = Field(..., description="LLM 生成的答案（Markdown 格式）。")
    question_type: QuestionType = Field(..., description="分類後的問題類型。")
    referenced_files: List[str] = Field(
        default_factory=list,
        description="本次回答所參考的專案檔案路徑列表。",
    )
    context_token_count: int = Field(
        default=0,
        description="本次送入 LLM 的上下文 Token 估算數量（供調試參考）。",
    )
    used_map_reduce_summary: bool = Field(
        default=False,
        description="是否使用了 Map-Reduce 精煉摘要作為上下文來源。",
    )


class SessionInfo(BaseModel):
    """Session 基本資訊，供 API 回應使用（不含敏感的程式碼內容）。

    Attributes:
        session_id: Session 的唯一識別碼（UUID）。
        project_name: 上傳的專案名稱（取自 ZIP 檔名）。
        file_count: Session 中快取的程式碼檔案數量。
        expires_at: Session 過期的 UTC 時間戳（ISO 8601 字串）。
        has_map_reduce_summary: 是否已預計算 Map-Reduce 精煉摘要。
    """

    session_id: str = Field(..., description="Session 的唯一識別碼（UUID）。")
    project_name: str = Field(..., description="上傳的專案名稱。")
    file_count: int = Field(..., description="快取的程式碼檔案數量。")
    expires_at: str = Field(..., description="Session 過期時間（ISO 8601 UTC）。")
    has_map_reduce_summary: bool = Field(
        default=False,
        description="是否已預計算 Map-Reduce 精煉摘要（代表該專案屬大型專案）。",
    )
