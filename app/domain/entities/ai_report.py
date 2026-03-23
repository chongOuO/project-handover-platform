"""AI 報告生成的 Domain 實體 (Entities)。

此模組定義 Phase 2 LangGraph AI 分析管線所產出的核心資料結構，
所有實體皆採用 Pydantic BaseModel 以確保型別安全與序列化支援。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SectionType(str, Enum):
    """分析區塊的種類識別列舉。

    Attributes:
        API_DOCS: API 使用文件區塊。
        ENV_GUIDE: 環境建置指南區塊。
    """

    API_DOCS = "api_docs"
    ENV_GUIDE = "env_guide"


class AnalysisSection(BaseModel):
    """代表 AI 生成報告中的單一分析區塊。

    Attributes:
        title: 此區塊的標題文字。
        content: AI 生成的 Markdown 格式內容本體。
        section_type: 區塊的種類識別 (``api_docs`` 或 ``env_guide``)。
        word_count: 內容的粗略字數估算，用於日誌記錄。
    """

    title: str = Field(..., description="報告區塊的標題。")
    content: str = Field(..., description="AI 生成的 Markdown 內容。")
    section_type: SectionType = Field(..., description="區塊種類識別。")
    word_count: int = Field(default=0, ge=0, description="內容字數的粗略估算。")

    def model_post_init(self, __context: object) -> None:
        """初始化後自動計算字數。

        Args:
            __context: Pydantic v2 model_post_init 標準參數（通常不使用）。
        """
        if self.word_count == 0 and self.content:
            object.__setattr__(self, "word_count", len(self.content.split()))


class AIReport(BaseModel):
    """聚合整份 AI 生成文件報告的根實體。

    Phase 2 管線的最終產出，包含兩份獨立的 Markdown 文件：
    API 使用文件與環境建置指南。

    Attributes:
        project_name: 被分析的目標專案名稱。
        api_docs: API 使用文件的 :class:`AnalysisSection` 資料物件。
        env_guide: 環境建置指南的 :class:`AnalysisSection` 資料物件。
        source_md_path: 被分析的來源 Markdown 檔案之原始路徑。
        api_docs_output_path: 生成的 API 文件輸出檔案路徑 (寫入後填入)。
        env_guide_output_path: 生成的環境指南輸出檔案路徑 (寫入後填入)。
        generated_at: 報告生成的 UTC 時間戳。
    """

    project_name: str = Field(..., description="被分析的專案名稱。")
    api_docs: AnalysisSection = Field(..., description="API 使用文件區塊。")
    env_guide: AnalysisSection = Field(..., description="環境建置指南區塊。")
    source_md_path: str = Field(..., description="來源 Markdown 檔案的路徑字串。")
    api_docs_output_path: Optional[str] = Field(
        None, description="生成的 API 文件輸出路徑（寫入檔案後填入）。"
    )
    env_guide_output_path: Optional[str] = Field(
        None, description="生成的環境指南輸出路徑（寫入檔案後填入）。"
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="報告生成的 UTC 時間戳。",
    )
