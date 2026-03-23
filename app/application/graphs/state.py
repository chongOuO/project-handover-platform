"""LangGraph 圖狀態 (GraphState) 定義。

GraphState 是整個 LangGraph 管線中各節點之間傳遞資料的唯一共享狀態容器，
採用 ``TypedDict`` 定義以確保型別安全並兼容 LangGraph 的狀態管理機制。
"""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    """LangGraph AI 分析管線的全局共享狀態。

    每個節點可讀取任意欄位，並透過回傳更新後的字典來寫入欄位。
    使用 ``total=False`` 使所有欄位均為可選，允許節點在首次呼叫時
    只含有初始欄位，後續節點逐步填充狀態。

    Attributes:
        project_name: 被分析的專案名稱（由 Service 層在觸發前填入）。
        source_md_path: 待讀取的 Markdown 來源文件絕對路徑字串。
        output_dir: 輸出目錄的絕對路徑字串。
        markdown_content: ``parse_markdown_node`` 讀取後填入的 Markdown 全文。
        api_docs_content: ``generate_api_docs_node`` 生成的 API 文件 Markdown。
        env_guide_content: ``generate_env_guide_node`` 生成的環境指南 Markdown。
        api_docs_output_path: ``format_output_node`` 寫入後填入的 API 文件路徑。
        env_guide_output_path: ``format_output_node`` 寫入後填入的環境指南路徑。
        error: 任何節點拋出的錯誤訊息字串（供調試用）。
    """

    project_name: str
    source_md_path: str
    output_dir: str
    markdown_content: str
    api_docs_content: str
    env_guide_content: str
    api_docs_output_path: Optional[str]
    env_guide_output_path: Optional[str]
    error: Optional[str]
