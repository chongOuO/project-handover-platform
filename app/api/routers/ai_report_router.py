"""API 路由 (Router)：AI 文件生成的 HTTP 進入點。

暴露 ``POST /api/v1/projects/generate-docs`` 端點，
接收 Phase 1 產出的 ``.md`` 報告路徑，呼叫 AI 分析管線，
並回傳兩份獨立文件（API 文件 + 環境指南）在伺服器上的輸出路徑。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, status

from app.api.schemas.ai_report_schema import GenerateDocsRequest, GenerateDocsResponse
from app.api.schemas.response import ErrorResponse
from app.application.services.ai_report_service import AIReportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["AI 文件生成"])

# 模組層級的 Service Singleton（與 Phase 1 Router 採相同設計慣例）
_service = AIReportService()


@router.post(
    "/generate-docs",
    status_code=status.HTTP_200_OK,
    summary="以 AI 分析 Markdown 報告，分別生成 API 文件與環境建置指南",
    description=(
        "接收 Phase 1 生成的 ``.md`` 來源報告路徑，"
        "透過 LangGraph 多節點呼叫 AI 語言模型，"
        "依序執行：\n\n"
        "1. 讀取 ``.md`` 來源文件內容。\n"
        "2. （並行）生成 **API 使用文件**（端點、請求/回應格式、curl 範例）。\n"
        "3. （並行）生成 **環境建置指南**（系統需求、安裝步驟、環境變數、排錯指引）。\n"
        "4. 將兩份文件分別寫入指定輸出目錄，檔名格式為 "
        "``{project_name}_api_docs.md`` 和 ``{project_name}_env_guide.md``。\n\n"
        "**前置需求**：伺服器環境需設定 ``API_KEY`` 環境變數。"
    ),
    response_model=GenerateDocsResponse,
    responses={
        200: {"description": "成功生成兩份文件，輸出至指定路徑。"},
        404: {"model": ErrorResponse, "description": "指定的 Markdown 來源文件不存在。"},
        502: {"model": ErrorResponse, "description": "AI 呼叫失敗。"},
        500: {"model": ErrorResponse, "description": "非預期的內部伺服器錯誤。"},
    },
)
async def generate_docs(request: GenerateDocsRequest) -> GenerateDocsResponse:
    """以 AI 分析 Markdown 來源報告，分別輸出兩份獨立文件。

    Args:
        request: 包含 ``md_file_path``（來源 .md）與 ``output_dir``（輸出目錄）的請求主體。

    Returns:
        :class:`~app.api.schemas.ai_report_schema.GenerateDocsResponse`，
        包含 ``api_docs_path`` 與 ``env_guide_path`` 兩個獨立的輸出檔案路徑。

    Raises:
        MarkdownSourceNotFoundError: 若 ``md_file_path`` 在伺服器上找不到 (→ 404)。
        LLMCallError: 若 Gemini API 金鑰未設定或呼叫失敗 (→ 502)。
    """
    md_path = Path(request.md_file_path)
    output_dir = Path(request.output_dir)

    logger.info(
        "收到文件生成請求：source=%s, output_dir=%s",
        md_path,
        output_dir,
    )

    report = await _service.generate(md_path=md_path, output_dir=output_dir)

    return GenerateDocsResponse(
        project_name=report.project_name,
        api_docs_path=report.api_docs_output_path or "",
        env_guide_path=report.env_guide_output_path or "",
        api_docs_word_count=report.api_docs.word_count,
        env_guide_word_count=report.env_guide.word_count,
        generated_at=report.generated_at,
    )
