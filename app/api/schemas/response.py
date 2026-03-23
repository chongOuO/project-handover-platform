"""專案交接平台的 API Response Schemas。

所有對外的公開回應模型全部基於 Pydantic v2，以便進行嚴格的資料型別驗證
並且供 FastAPI 自動生成對應的 OpenAPI 文件 (Swagger)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """由全域 exceptions handler 統一拋出的標準化錯誤回傳結構。

    Attributes:
        error_code: 機器可讀的錯誤代碼標識 (例如：``"INVALID_ZIP_FILE"``)。
        message: 供人類閱讀閱讀的錯誤描述。
        detail: 可選詳細資訊的擴充上下文，如出錯的欄位名稱、或上游發生的原始錯誤訊息。
    """

    error_code: str = Field(..., examples=["INVALID_ZIP_FILE"])
    message: str = Field(..., examples=["上傳的檔案不是一個有效的 ZIP 壓縮檔。"])
    detail: Optional[str] = Field(None, examples=["Bad magic number for file header"])

    model_config = {"json_schema_extra": {"title": "ErrorResponse"}}


class AnalyzeResponse(BaseModel):
    """API ``POST /api/v1/projects/analyze`` 回傳的成功回應。

    Attributes:
        project_name: 由上傳 ZIP 附檔移除掉副檔名後自動推斷得出的專案名。
        file_count: 當套過濾器處理後，會收錄並輸出至報告中的程式碼檔案數量。
        total_files_in_zip: 在這個 ZIP 壓縮包裡頭找到的所有檔案總數量。
        skipped_files: 被忽略而不收錄過濾規則所被除掉的數量。
        markdown_report: 用純文字形式呈現 UTF-8 編碼形式之 Markdown 報告。
        generated_at: 表示該報告生成當下的 UTC 當下時間。
    """

    project_name: str = Field(..., examples=["my-awesome-project"])
    file_count: int = Field(..., ge=0, examples=[12])
    total_files_in_zip: int = Field(..., ge=0, examples=[40])
    skipped_files: int = Field(..., ge=0, examples=[28])
    markdown_report: str = Field(..., description="完整的 Markdown 報告原始內容。")
    generated_at: datetime = Field(
        ...,
        examples=["2026-03-16T11:39:59+08:00"],
        description="分析任務完成當下的 UTC 國際標準時間區段。",
    )

    model_config = {"json_schema_extra": {"title": "AnalyzeResponse"}}


class FullAnalysisResponse(BaseModel):
    """``POST /api/v1/projects/analyze-and-generate`` 的成功回應模型。

    整合 Phase 1 + Phase 2 的完整管線結果，實際由 :class:`FullPipelineService`
    計算後填入。

    Attributes:
        project_name: 由 ZIP 檔名推斷的專案名稱。
        code_file_count: Phase 1 過濾後納入分析的程式碼檔案數量。
        total_files_in_zip: ZIP 內的總檔案數量。
        api_docs_path: AI 生成的 API 使用文件輸出路徑。
        env_guide_path: AI 生成的環境建置指南輸出路徑。
        api_docs_word_count: API 文件的粗略字數估算。
        env_guide_word_count: 環境指南的粗略字數估算。
        generated_at: 整個管線完成的 UTC 時間戳。
    """

    project_name: str = Field(..., examples=["my_project"])
    code_file_count: int = Field(..., ge=0, examples=[12])
    total_files_in_zip: int = Field(..., ge=0, examples=[40])
    api_docs_path: str = Field(
        ...,
        description="AI 生成的 API 使用文件輸出路徑（伺服器本地）。",
        examples=["/tmp/output/my_project_api_docs.md"],
    )
    env_guide_path: str = Field(
        ...,
        description="AI 生成的環境建置指南輸出路徑（伺服器本地）。",
        examples=["/tmp/output/my_project_env_guide.md"],
    )
    api_docs_word_count: int = Field(default=0, ge=0, description="API 文件字數估算。")
    env_guide_word_count: int = Field(default=0, ge=0, description="環境指南字數估算。")
    generated_at: datetime = Field(
        ...,
        description="整個管線完成的 UTC 時間戳。",
        examples=["2026-03-18T07:08:00+00:00"],
    )

    model_config = {"json_schema_extra": {"title": "FullAnalysisResponse"}}
