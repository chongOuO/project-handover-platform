"""Q&A API 層的 Pydantic Request / Response Schemas。

遵循現有 ``app/api/schemas/response.py`` 的設計慣例，
所有 Response 均包裝於統一的成功/錯誤格式中。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """POST /qa/sessions/{session_id}/ask 的請求體。

    Attributes:
        question: 使用者輸入的問題字串（1～2000 字元）。
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="針對已上傳專案的問題字串。",
        examples=["這個專案的資料庫連線是在哪裡設定的？"],
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class SessionCreatedResponse(BaseModel):
    """POST /qa/sessions 成功後的回應體。

    Attributes:
        session_id: 建立的 Session 唯一識別碼（UUID）。
        project_name: 上傳的專案名稱（取自 ZIP 檔名）。
        file_count: Session 中快取的程式碼檔案數量。
        expires_at: Session 過期的 UTC 時間（ISO 8601）。
        has_map_reduce_summary: 是否已預計算 Map-Reduce 摘要（大型專案才為 True）。
        message: 操作結果說明。
    """

    session_id: str = Field(..., description="Session 唯一識別碼（UUID）。")
    project_name: str = Field(..., description="上傳的專案名稱。")
    file_count: int = Field(..., description="快取的程式碼檔案數量。")
    expires_at: str = Field(..., description="Session 過期時間（ISO 8601 UTC）。")
    has_map_reduce_summary: bool = Field(
        default=False,
        description="是否已預計算 Map-Reduce 精煉摘要（代表大型專案）。",
    )
    message: str = Field(default="Session 建立成功，可開始提問。")


class AskResponse(BaseModel):
    """POST /qa/sessions/{session_id}/ask 成功後的回應體。

    Attributes:
        answer: LLM 生成的答案（Markdown 格式）。
        question_type: 分類後的問題類型。
        referenced_files: 本次回答所參考的檔案路徑列表。
        context_token_count: 送入 LLM 的上下文 Token 估算數量。
        used_map_reduce_summary: 是否使用了 Map-Reduce 精煉摘要作為上下文。
    """

    answer: str = Field(..., description="LLM 生成的答案（Markdown 格式）。")
    question_type: str = Field(..., description="問題分類結果。")
    referenced_files: List[str] = Field(
        default_factory=list,
        description="本次回答所參考的程式碼檔案路徑列表。",
    )
    context_token_count: int = Field(
        default=0,
        description="送入 LLM 的上下文估算 Token 數量（供調試）。",
    )
    used_map_reduce_summary: bool = Field(
        default=False,
        description="是否使用了 Map-Reduce 精煉摘要作為上下文來源。",
    )


class DeleteSessionResponse(BaseModel):
    """DELETE /qa/sessions/{session_id} 成功後的回應體。

    Attributes:
        session_id: 被刪除的 Session 識別碼。
        message: 操作結果說明。
    """

    session_id: str = Field(..., description="已刪除的 Session 識別碼。")
    message: str = Field(default="Session 已成功刪除。")
