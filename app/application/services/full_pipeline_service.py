"""完整整合管線 Service (Full Pipeline Service)。

串聯 Phase 1（ZIP → Markdown）與 Phase 2（Markdown → AI 文件）兩個管線，
讓呼叫端只需傳入一個 ZIP 壓縮檔，即可取得兩份 AI 生成的技術文件。

管線流向：
    ZIP bytes
      → ProjectAnalysisService.analyze()        # Phase 1：解析、過濾、建樹
      → ProjectAnalysisService.render_markdown() # Phase 1：渲染 Markdown 字串
      → AIReportService.generate_from_content()  # Phase 2：LangGraph 生成兩份文件
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.application.graphs.ai_analysis_graph import build_graph
from app.application.services.project_analysis_service import ProjectAnalysisService
from app.domain.entities.ai_report import AIReport, AnalysisSection, SectionType
from app.infrastructure.adapters.file_filter import FilterMode

logger = logging.getLogger(__name__)


class FullPipelineService:
    """串聯 Phase 1 + Phase 2 的完整整合 Application Service。

    只需一次呼叫即可完成「上傳 ZIP → 生成導讀 Markdown → AI 分析輸出兩份技術文件」
    的全流程，對 Router 層隱藏兩個 Phase 的內部細節。

    Example::

        service = FullPipelineService()
        report = await service.analyze_and_generate(
            zip_bytes=b"...",
            filename="my_project.zip",
            output_dir=Path("/tmp/output"),
        )
        print(report.api_docs_output_path)
        print(report.env_guide_output_path)
    """

    def __init__(self) -> None:
        """預先初始化 Phase 1 Service 並編譯 LangGraph。

        **邏輯重點**：兩個 Service 都在應用啟動時初始化（Singleton 模式），
        LangGraph 只編譯一次避免重複開銷。
        """
        self._phase1 = ProjectAnalysisService()
        self._graph = build_graph()
        logger.info("FullPipelineService 初始化完成。")

    async def analyze_and_generate(
        self,
        zip_bytes: bytes,
        filename: str,
        output_dir: Path,
    ) -> AIReport:
        """執行完整的 Phase 1 + Phase 2 整合管線。

        Args:
            zip_bytes: 上傳的 ZIP 檔案之原始位元組資料。
            filename: 上傳時的原始檔名（例如：``"my_project.zip"``）。
            output_dir: AI 生成的兩份 Markdown 文件的輸出目錄，不存在則自動建立。

        Returns:
            包含兩份文件輸出路徑的 :class:`~app.domain.entities.ai_report.AIReport` 實體。

        Raises:
            FileSizeLimitExceededError: ZIP 超過 50 MB。
            InvalidZipFileError: 上傳的不是有效 ZIP。
            EmptyProjectError: 過濾後無程式碼檔案。
            LLMCallError: Gemini API 呼叫失敗。
        """
        # ── Phase 1：ZIP → ProjectStructure → Markdown 字串 ───────────────────
        logger.info("[FullPipeline] Phase 1 啟動：%s（過濾模式：API_DOCS）", filename)
        structure = await self._phase1.analyze(
            zip_bytes=zip_bytes,
            filename=filename,
            filter_mode=FilterMode.API_DOCS,
        )
        markdown_content = self._phase1.render_markdown(structure)
        project_name = structure.project_name
        logger.info(
            "[FullPipeline] Phase 1 完成：%s（%d 個程式碼檔案，Markdown %d 字元）",
            project_name,
            structure.code_file_count,
            len(markdown_content),
        )

        # ── Phase 2：Markdown 字串直傳 LangGraph → 兩份 AI 文件 ─────────────────
        logger.info("[FullPipeline] Phase 2 啟動：LangGraph AI 分析管線")
        initial_state = {
            "project_name": project_name,
            # 直傳 markdown_content，parse_markdown_node 將自動跳過磁碟讀取
            "markdown_content": markdown_content,
            "source_md_path": f"<in-memory:{filename}>",
            "output_dir": str(output_dir.resolve()),
        }

        final_state = await self._graph.ainvoke(initial_state)

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
            source_md_path=f"<in-memory:{filename}>",
            api_docs_output_path=final_state.get("api_docs_output_path"),
            env_guide_output_path=final_state.get("env_guide_output_path"),
        )

        logger.info(
            "[FullPipeline] 完成 → API 文件：%s | 環境指南：%s",
            report.api_docs_output_path,
            report.env_guide_output_path,
        )
        return report
