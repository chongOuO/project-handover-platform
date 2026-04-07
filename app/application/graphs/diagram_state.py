"""Diagram 管線的狀態定義。"""

from __future__ import annotations
from typing import Optional
from typing_extensions import TypedDict

class DiagramGraphState(TypedDict, total=False):
    """Diagram AI 分析管線的全局共享狀態。

    Attributes:
        project_name: 待分析專案名稱。
        markdown_content: Phase 1 解析出的純文字巨量原始碼文檔（作為輸入）。
        content_token_estimate: 對 markdown_content 的 Token 數估算。
        compression_applied: 是否對內容進行了壓縮處理。
        has_database: 是否偵測到資料庫相關關鍵字。
        architecture_diagram: 產出之 Mermaid 系統架構圖 (graph TD)。
        er_diagram: 產出之 Mermaid ER 圖 (erDiagram)。若無則為 None。
        error: 處理過程任何例外錯誤。
    """
    project_name: str
    markdown_content: str
    content_token_estimate: int
    compression_applied: bool
    has_database: bool
    architecture_diagram: str
    er_diagram: Optional[str]
    error: Optional[str]
