"""Application 層 AI 報告生成 Service。

協調 LangGraph AI 分析管線的執行：接收使用者請求（來源 .md 路徑與輸出目錄），
觸發 Graph 的異步執行，並從最終 State 中取出輸出路徑後回傳給 Router 層。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.application.graphs.ai_analysis_graph import build_graph
from app.domain.entities.ai_report import AIReport, AnalysisSection, SectionType

logger = logging.getLogger(__name__)


class AIReportService:
    """協調 LangGraph 管線執行的 Application Service。

    此 Service 是 Router 層與 LangGraph 圖之間的唯一介面，
    負責構建初始 State、執行圖、並將結果包裝為 :class:`~app.domain.entities.ai_report.AIReport`。

    Example::

        service = AIReportService()
        report = await service.generate(
            md_path=Path("/path/to/project_report.md"),
            output_dir=Path("/path/to/output"),
        )
        print(report.api_docs_output_path)
        print(report.env_guide_output_path)
    """

    def __init__(self) -> None:
        """初始化 AIReportService，預先編譯 LangGraph。

        **邏輯重點**：Graph 在 Service 初始化時一次性編譯完成，
        後續每次請求只需執行 ``ainvoke()``，避免重複編譯開銷。
        """
        self._graph = build_graph()
        logger.info("AIReportService 初始化完成，LangGraph 已編譯。")

    async def generate(self, md_path: Path, output_dir: Path) -> AIReport:
        """執行 AI 分析管線並回傳最終報告實體。

        Args:
            md_path: Phase 1 生成的 ``.md`` 來源文件的絕對路徑。
            output_dir: 兩份輸出文件（API 文件、環境指南）的儲存目錄。

        Returns:
            包含兩份文件輸出路徑的 :class:`~app.domain.entities.ai_report.AIReport` 實體。

        Raises:
            MarkdownSourceNotFoundError: 若 ``md_path`` 不存在。
            LLMCallError: 若 Gemini API 呼叫失敗。
        """
        project_name = md_path.stem.removesuffix("_report") if "_report" in md_path.stem else md_path.stem

        initial_state = {
            "project_name": project_name,
            "source_md_path": str(md_path.resolve()),
            "output_dir": str(output_dir.resolve()),
        }

        logger.info(
            "觸發 AI 分析管線：project=%s, source=%s, output=%s",
            project_name,
            initial_state["source_md_path"],
            initial_state["output_dir"],
        )

        final_state = await self._graph.ainvoke(initial_state)

        # 從圖的最終 State 中取回輸出路徑，組裝成 Domain 實體回傳
        report = AIReport(
            project_name=project_name,
            api_docs=AnalysisSection(
                title="API 使用文件",
                content=final_state.get("api_docs_content", ""),
                section_type=SectionType.API_DOCS,
            ),
            env_guide=AnalysisSection(
                title="環境建置指南",
                content=final_state.get("env_guide_content", ""),
                section_type=SectionType.ENV_GUIDE,
            ),
            source_md_path=str(md_path),
            api_docs_output_path=final_state.get("api_docs_output_path"),
            env_guide_output_path=final_state.get("env_guide_output_path"),
        )

        logger.info(
            "AI 分析管線執行完成 → API 文件：%s | 環境指南：%s",
            report.api_docs_output_path,
            report.env_guide_output_path,
        )
        return report
