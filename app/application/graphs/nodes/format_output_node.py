"""LangGraph 節點 4：格式化並輸出最終報告文件。

從 State 中取得兩份 AI 生成內容（``api_docs_content`` 和 ``env_guide_content``），
組裝成 :class:`~app.domain.entities.ai_report.AIReport` 實體，
並透過 :class:`~app.infrastructure.adapters.report_writer.ReportWriter`
分別寫出為兩份獨立的 Markdown 文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.application.graphs.state import GraphState
from app.domain.entities.ai_report import AIReport, AnalysisSection, SectionType
from app.infrastructure.adapters.report_writer import ReportWriter

logger = logging.getLogger(__name__)

_writer = ReportWriter()


async def format_output_node(state: GraphState) -> GraphState:
    """組裝 AIReport 並將兩份文件分別寫入磁碟。

    **邏輯重點**：此節點是管線的最後一道「效果閘門」(Effect Gate)，
    負責所有的寫入 I/O 副作用，前面的節點只做純粹的資料轉換。
    將 API 文件與環境指南分開寫入兩個獨立 ``.md`` 檔案，
    且輸出路徑會被回寫進 State，供 Service 層取回並回傳給呼叫端。

    Args:
        state: 需包含 ``api_docs_content``、``env_guide_content``、
            ``output_dir`` 與 ``project_name`` 欄位。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        新增了 ``api_docs_output_path`` 與 ``env_guide_output_path`` 兩個路徑欄位。
    """
    logger.info("[format_output_node] 組裝 AIReport 並寫出兩份文件...")

    project_name = state["project_name"]
    output_dir = Path(state["output_dir"])

    api_section = AnalysisSection(
        title="API 使用文件",
        content=state["api_docs_content"],
        section_type=SectionType.API_DOCS,
    )
    env_section = AnalysisSection(
        title="環境建置指南",
        content=state["env_guide_content"],
        section_type=SectionType.ENV_GUIDE,
    )

    report = AIReport(
        project_name=project_name,
        api_docs=api_section,
        env_guide=env_section,
        source_md_path=state["source_md_path"],
    )

    api_path, env_path = await _writer.write(report, output_dir)

    logger.info(
        "[format_output_node] 寫出完成 → API 文件：%s | 環境指南：%s",
        api_path,
        env_path,
    )

    return {
        "api_docs_output_path": str(api_path),
        "env_guide_output_path": str(env_path),
    }
