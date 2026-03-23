"""Phase 2 AI 文件生成功能的 API Request/Response Schema。

使用 Pydantic v2 定義，確保 FastAPI 能自動生成對應的 OpenAPI 文件，
並提供嚴格的型別驗證與序列化支援。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class   GenerateDocsRequest(BaseModel):
    """``POST /api/v1/projects/generate-docs`` 的請求主體模型。

    Attributes:
        md_file_path: Phase 1 生成的 ``.md`` 報告文件在伺服器上的完整絕對路徑。
        output_dir: 兩份生成文件的輸出目錄路徑（伺服器本地路徑），若不存在將自動建立。
    """

    md_file_path: str = Field(
        ...,
        description="Phase 1 生成的 .md 報告文件的伺服器絕對路徑。",
        examples=["/Users/k/Desktop/code/my_project_report.md"],
    )
    output_dir: str = Field(
        ...,
        description="兩份輸出文件（API 文件 + 環境指南）的儲存目錄路徑，不存在將自動建立。",
        examples=["/Users/k/Desktop/code/output"],
    )

    model_config = {"json_schema_extra": {"title": "GenerateDocsRequest"}}


class GenerateDocsResponse(BaseModel):
    """``POST /api/v1/projects/generate-docs`` 的成功回應模型。

    Attributes:
        project_name: 從來源 .md 檔名推斷出的專案名稱。
        api_docs_path: 已寫入完成之 API 使用文件的伺服器本地完整路徑。
        env_guide_path: 已寫入完成之環境建置指南的伺服器本地完整路徑。
        api_docs_word_count: API 文件的粗略字數統計。
        env_guide_word_count: 環境指南的粗略字數統計。
        generated_at: 報告生成完成的 UTC 時間戳。
    """

    project_name: str = Field(..., examples=["my_project"])
    api_docs_path: str = Field(
        ...,
        description="API 使用文件的輸出路徑（伺服器本地）。",
        examples=["/Users/k/Desktop/code/output/my_project_api_docs.md"],
    )
    env_guide_path: str = Field(
        ...,
        description="環境建置指南的輸出路徑（伺服器本地）。",
        examples=["/Users/k/Desktop/code/output/my_project_env_guide.md"],
    )
    api_docs_word_count: int = Field(default=0, ge=0, description="API 文件字數估算。")
    env_guide_word_count: int = Field(default=0, ge=0, description="環境指南字數估算。")
    generated_at: datetime = Field(
        ...,
        description="報告生成完成的 UTC 時間戳。",
        examples=["2026-03-18T06:56:00+00:00"],
    )

    model_config = {"json_schema_extra": {"title": "GenerateDocsResponse"}}
