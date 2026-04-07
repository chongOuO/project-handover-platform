"""Diagram Application Service.

負責將 Router 收到上傳的檔案與請求封裝後，橋接 Phase 1 
的核心分析邏輯與 Phase 2 Diagram LangGraph 生成管線，
最終組裝 DiagramResponse。
"""

from __future__ import annotations

import logging
from typing import Any

from app.api.schemas.diagram_schema import DiagramResponse
from app.application.graphs.diagram_graph import build_diagram_graph
from app.application.services.project_analysis_service import ProjectAnalysisService

logger = logging.getLogger(__name__)


class DiagramService:
    """協調分析 ZIP 與產出 Mermaid.js 圖表的 Service。

    將 Phase 1 的過濾組件解析結果導入 DiagramGraph，返回結果給 Router。
    """

    def __init__(self) -> None:
        """初始化。

        由於是單一進程的 FastAPI，通常在 Router 啟動時作為模組層級實例化，
        一次性建構 Diagram Graph 並重用 ProjectAnalysisService 機制。
        """
        self._phase1 = ProjectAnalysisService()
        self._graph = build_diagram_graph()
        logger.info("DiagramService 初始化完成。")

    async def generate_diagrams(self, zip_bytes: bytes, filename: str) -> DiagramResponse:
        """完整執行從 ZIP 讀取到圖表產出的工作流程。

        Args:
            zip_bytes: ZIP 原始二進位資料。
            filename: 使用者上傳時之原始檔名。

        Returns:
            符合 :class:`~app.api.schemas.diagram_schema.DiagramResponse` 的 Pydantic 物件。

        Raises:
            UnsupportedFileTypeError: 型別不符
            InvalidZipFileError: 有效性異常
            EmptyProjectError: 內含空碼
        """
        # 1. Phase 1
        logger.info("[DiagramService] 開始 Phase 1: 解析 ZIP 專案 %s", filename)
        structure = await self._phase1.analyze(zip_bytes=zip_bytes, filename=filename)
        markdown_content = self._phase1.render_markdown(structure)
        project_name = structure.project_name

        # 2. Graph Pipeline
        logger.info("[DiagramService] 開始 Phase 2: Diagram 管線生成 %s", project_name)

        # Token 估算
        content_token_estimate = int(len(markdown_content) / 3.5)
        logger.info("[DiagramService] content_token_estimate: %d", content_token_estimate)

        initial_state = {
            "project_name": project_name,
            "markdown_content": markdown_content,
            "content_token_estimate": content_token_estimate,
        }

        # 發送至 Graph 處理
        final_state = await self._graph.ainvoke(initial_state)

        # 3. 回覆模型組裝
        logger.info("[DiagramService] 生成完成，準備組裝 Response。")
        return DiagramResponse(
            project_name=project_name,
            has_database=final_state.get("has_database", False),
            architecture_diagram=final_state.get("architecture_diagram", ""),
            er_diagram=final_state.get("er_diagram"),
        )
