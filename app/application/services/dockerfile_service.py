"""Dockerfile Application Service。

負責將 Router 收到上傳的 ZIP 檔案與請求封裝後，
協調 Phase 1 核心解析邏輯與 DockerfileGraph LangGraph 管線，
最終組裝並回傳 DockerfileResponse。
"""

from __future__ import annotations

import logging

from app.api.schemas.dockerfile_schema import DockerfileResponse
from app.application.graphs.dockerfile_graph import build_dockerfile_graph
from app.application.services.project_analysis_service import ProjectAnalysisService

logger = logging.getLogger(__name__)


class DockerfileService:
    """協調 ZIP 分析與 Dockerfile / docker-compose 生成的 Application Service。

    採用與 DiagramService 相同的「Phase 1 解析 → Graph 管線 → 組裝回應」模式。
    模組層級單例策略：由 Router 在應用啟動時實例化，後續重用，
    避免每次請求重建 LangGraph 編譯後的管線物件。
    """

    def __init__(self) -> None:
        """初始化 Phase 1 服務與 Dockerfile LangGraph 管線。"""
        self._phase1 = ProjectAnalysisService()
        self._graph = build_dockerfile_graph()
        logger.info("DockerfileService 初始化完成。")

    async def generate_dockerfile(
        self,
        zip_bytes: bytes,
        filename: str,
    ) -> DockerfileResponse:
        """完整執行從 ZIP 讀取到 Dockerfile / docker-compose 生成的工作流程。

        Args:
            zip_bytes: ZIP 原始二進位資料。
            filename: 使用者上傳時之原始檔名（用於 Phase 1 解析與日誌記錄）。

        Returns:
            符合 :class:`~app.api.schemas.dockerfile_schema.DockerfileResponse` 的 Pydantic 物件。

        Raises:
            UnsupportedFileTypeError: 型別不符（由 Router 層預先攔截）。
            InvalidZipFileError: ZIP 有效性異常。
            EmptyProjectError: ZIP 內無可分析的原始碼。
        """
        # 1. Phase 1：ZIP 解析 → Markdown
        logger.info("[DockerfileService] 開始 Phase 1：解析 ZIP 專案 %s", filename)
        structure = await self._phase1.analyze(zip_bytes=zip_bytes, filename=filename)
        markdown_content = self._phase1.render_markdown(structure)
        project_name = structure.project_name

        # 2. Token 估算
        content_token_estimate = int(len(markdown_content) / 3.5)
        logger.info(
            "[DockerfileService] Phase 1 完成。project_name=%s, token_estimate=%d",
            project_name,
            content_token_estimate,
        )

        # 3. 觸發 Dockerfile LangGraph 管線
        logger.info("[DockerfileService] 開始 Phase 2：Dockerfile 管線生成 %s", project_name)
        initial_state = {
            "project_name": project_name,
            "markdown_content": markdown_content,
            "content_token_estimate": content_token_estimate,
        }
        final_state = await self._graph.ainvoke(initial_state)

        # 4. 組裝 Response
        logger.info("[DockerfileService] 管線完成，準備組裝 DockerfileResponse。")
        return DockerfileResponse(
            project_name=project_name,
            language=final_state.get("detected_language", "unknown"),
            framework=final_state.get("detected_framework"),
            base_image=final_state.get("base_image", "debian:bookworm-slim"),
            has_database=final_state.get("has_database", False),
            detected_db_type=final_state.get("detected_db_type"),
            dockerfile_content=final_state.get("dockerfile_content", ""),
            dockerignore_content=final_state.get("dockerignore_content"),
            compose_content=final_state.get("compose_content", ""),
        )
