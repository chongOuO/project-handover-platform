"""API 回應結構定義：圖表生成 (Diagrams)。

此模組定義與 Mermaid.js 架構圖與 ER 圖相關的 Pydantic 模型，
主要用於 ``DiagramRouter`` 的回傳資料結構驗證。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DiagramResponse(BaseModel):
    """圖表產出回應物件 (Diagram Response)。

    封裝經由 LangGraph 分析後所生成的系統架構圖與關聯式資料庫 ER 圖。
    提供可以直接給前端或工具渲染的 Mermaid.js 語法。
    """
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "project_name": "my_awesome_project",
                "has_database": True,
                "architecture_diagram": "graph TD\n  A[FastAPI] --> B[Service]\n",
                "er_diagram": "erDiagram\n  USER ||--o{ POST : writes\n",
                "generated_at": "2026-04-07T12:00:00.000Z"
            }
        }
    )

    project_name: str = Field(
        ...,
        description="分析目標專案之名稱（通常為 ZIP 檔名剔除副檔名）。",
        example="my_awesome_project",
    )
    has_database: bool = Field(
        ...,
        description="此專案是否偵測到資料庫相關程式碼（影響是否生成 ER 圖）。",
        example=True,
    )
    architecture_diagram: str = Field(
        ...,
        description="系統架構圖的 Mermaid.js (graph TD) 語法字串。前端可直接渲染。",
    )
    er_diagram: Optional[str] = Field(
        default=None,
        description="資料庫的關聯 ER 圖 (erDiagram) 語法字串。若未偵測到資料庫則為 null。",
    )
    generated_at: datetime = Field(
        default_factory=datetime.now,
        description="文件產出伺服器時間 (ISO 8601 格式)。",
    )
