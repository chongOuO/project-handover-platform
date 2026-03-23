"""API 路由 (Router)：專案分析之 HTTP 進入點。

暴露兩個端點：
- ``POST /api/v1/projects/analyze``：**（測試用）** ZIP → Markdown 報告，直接下載 ``.md``。
- ``POST /api/v1/projects/analyze-and-generate``：**（整合）** ZIP → Markdown → AI 分析，
  輸出 **兩份獨立** ``.md`` 文件（API 使用文件 + 環境建置指南）。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from app.api.schemas.response import ErrorResponse, FullAnalysisResponse
from app.application.services.full_pipeline_service import FullPipelineService
from app.application.services.project_analysis_service import ProjectAnalysisService
from app.domain.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])

# 模組層級的服務執行個體（Singleton 模式；FastAPI 單一進程情境）
_service = ProjectAnalysisService()
_full_service = FullPipelineService()


# ─────────────────────────────────────────────────────────────────────────────
# 端點 1：測試用 — ZIP → Markdown 報告下載
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    summary="【測試】分析 ZIP 並下載 Markdown 報告",
    description=(
        "**（測試端點）** 上傳 `.zip` 壓縮檔，執行 Phase 1 管線：\n\n"
        "1. 解壓縮至暫存區。\n"
        "2. 智慧過濾雜訊檔案（圖片、Binary、Git 系統）。\n"
        "3. 生成目錄樹與程式碼內容嵌入（>2000 Token 自動截斷）。\n"
        "4. 直接以 `.md` 附件回傳下載。\n\n"
        "此端點**不呼叫 AI**，僅用於驗證 Phase 1 輸出是否正確。"
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"text/markdown": {}}, "description": "成功回傳 Markdown 報告附件。"},
        415: {"model": ErrorResponse, "description": "上傳檔案非 .zip 格式。"},
        413: {"model": ErrorResponse, "description": "超過 50 MB 上限。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP 或過濾後無程式碼檔案。"},
        500: {"model": ErrorResponse, "description": "非預期的內部錯誤。"},
    },
)
async def analyze_project(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮檔。"),
) -> FileResponse:
    """分析並將上傳的 ZIP 壓縮專案渲染成 Markdown 報告後下載。

    Args:
        file: FastAPI 解析的 multipart 上傳檔案物件。

    Returns:
        以 ``FileResponse`` 包裝的 ``.md`` 附件，下載檔名為 ``{project_name}_report.md``。

    Raises:
        UnsupportedFileTypeError: 非 .zip 格式。
        FileSizeLimitExceededError: 超過 50 MB。
        InvalidZipFileError: 非有效 ZIP。
        EmptyProjectError: 過濾後無程式碼檔案。
    """
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info("[analyze] 收到檔案：'%s' (content_type=%s)", filename, file.content_type)

    zip_bytes: bytes = await file.read()
    structure = await _service.analyze(zip_bytes=zip_bytes, filename=filename)
    markdown_report = _service.render_markdown(structure)

    download_filename = f"{structure.project_name}_report.md"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False)
    try:
        tmp.write(markdown_report)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    logger.info("[analyze] 回傳 '%s' (tmp=%s)", download_filename, tmp_path)
    return FileResponse(
        path=tmp_path,
        media_type="application/octet-stream",
        filename=download_filename,
        background=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 端點 2：整合 — ZIP → Markdown → AI 生成兩份技術文件
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/analyze-and-generate",
    status_code=status.HTTP_200_OK,
    summary="整合管線：分析 ZIP 並以 AI 生成 API 文件與環境指南",
    description=(
        "**（整合管線）** 上傳 `.zip`，完整執行兩個 Phase：\n\n"
        "**Phase 1**（ZIP → Markdown）：\n"
        "- 解壓縮、智慧過濾、建立目錄樹、渲染 Markdown。\n\n"
        "**Phase 2**（Markdown → AI 文件，透過 LangGraph）：\n"
        "- `generate_api_docs_node`：生成 API 使用文件。\n"
        "- `generate_env_guide_node`：生成環境建置指南。\n"
        "- 兩者**並行執行**後合併輸出為兩份獨立 `.md` 檔案。\n\n"
        "**前置需求**：伺服器需設定 `GOOGLE_API_KEY` 環境變數。\n\n"
        "輸出檔名格式：\n"
        "- `{project_name}_api_docs.md`\n"
        "- `{project_name}_env_guide.md`"
    ),
    response_model=FullAnalysisResponse,
    responses={
        200: {"description": "成功生成兩份文件，回傳輸出路徑。"},
        415: {"model": ErrorResponse, "description": "上傳檔案非 .zip 格式。"},
        413: {"model": ErrorResponse, "description": "超過 50 MB 上限。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP 或過濾後無程式碼檔案。"},
        502: {"model": ErrorResponse, "description": "AI 語言模型 API 呼叫失敗。"},
        500: {"model": ErrorResponse, "description": "非預期的內部錯誤。"},
    },
)
async def analyze_and_generate(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮檔。"),
    output_dir: str = Form(
        default=str(Path.home() / "Desktop" / "ai_docs"),
        description="兩份輸出文件的儲存目錄路徑（伺服器本地），不存在將自動建立。",
    ),
) -> FullAnalysisResponse:
    """執行完整 Phase 1 + Phase 2 整合管線並回傳兩份文件的輸出路徑。

    Args:
        file: FastAPI 解析的 multipart 上傳 ZIP 檔案物件。
        output_dir: 兩份 AI 文件的輸出目錄（Form 欄位，有預設值）。

    Returns:
        :class:`~app.api.schemas.response.FullAnalysisResponse`，
        包含 ``api_docs_path`` 與 ``env_guide_path`` 兩個獨立輸出路徑。

    Raises:
        UnsupportedFileTypeError: 非 .zip 格式 (→ 415)。
        FileSizeLimitExceededError: 超過 50 MB (→ 413)。
        InvalidZipFileError: 非有效 ZIP (→ 422)。
        EmptyProjectError: 過濾後無程式碼檔案 (→ 422)。
        LLMCallError: Gemini API 呼叫失敗 (→ 502)。
    """
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info(
        "[analyze-and-generate] 收到 '%s'，輸出目錄：%s",
        filename,
        output_dir,
    )

    zip_bytes: bytes = await file.read()
    report = await _full_service.analyze_and_generate(
        zip_bytes=zip_bytes,
        filename=filename,
        output_dir=Path(output_dir),
    )

    return FullAnalysisResponse(
        project_name=report.project_name,
        code_file_count=report.api_docs.word_count,   # 用 word_count 做字數統計
        total_files_in_zip=0,                          # FullPipelineService 可擴充傳入
        api_docs_path=report.api_docs_output_path or "",
        env_guide_path=report.env_guide_output_path or "",
        api_docs_word_count=report.api_docs.word_count,
        env_guide_word_count=report.env_guide.word_count,
        generated_at=report.generated_at,
    )

