"""圖表生成 API 路由 (Diagram Router)。

提供兩個端點：
- ``POST /api/v1/diagrams/generate``：回傳 JSON，包含 Mermaid 語法字串。
- ``POST /api/v1/diagrams/generate-and-download``：回傳可直接下載的 ``.md`` 附件。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.schemas.diagram_schema import DiagramResponse
from app.api.schemas.response import ErrorResponse
from app.application.services.diagram_service import DiagramService
from app.domain.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/diagrams", tags=["Diagrams"])

# 模組層級執行個體 (Singleton)
_diagram_service = DiagramService()


def _render_mermaid_markdown(result: DiagramResponse) -> str:
    """將 DiagramResponse 渲染成可閱讀的 Mermaid Markdown 文件。"""
    lines = [
        f"# {result.project_name} — 系統圖表",
        "",
        f"> 生成時間：{result.generated_at.isoformat()}",
        f"> 資料庫偵測：{'是' if result.has_database else '否'}",
        "",
        "---",
        "",
        "## 系統架構圖",
        "",
        "```mermaid",
        result.architecture_diagram,
        "```",
    ]
    if result.er_diagram:
        lines += [
            "",
            "---",
            "",
            "## 資料庫 ER 圖",
            "",
            "```mermaid",
            result.er_diagram,
            "```",
        ]
    return "\n".join(lines)


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    summary="生成 Mermaid 系統架構圖與 ER 圖（JSON）",
    description=(
        "上傳專案的 `.zip` 壓縮檔，回傳 AI 分析產生的 Mermaid.js 圖表語法（JSON 格式）。\n\n"
        "流程：解壓縮 → 過濾 → Markdown 化 → Token 截斷保護 → AI 生成 `graph TD` 架構圖 → "
        "(若有 DB) 生成 `erDiagram` → 語法驗證。\n\n"
        "回傳純 JSON，包含可供前端直接渲染的 Mermaid 語法字串。"
    ),
    response_model=DiagramResponse,
    responses={
        200: {"description": "成功產出圖表。"},
        413: {"model": ErrorResponse, "description": "超過上傳檔案大小限制。"},
        415: {"model": ErrorResponse, "description": "上傳非 .zip 格式之檔案。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP，或該專案內沒有找到適用的程式碼原始檔。"},
        500: {"model": ErrorResponse, "description": "非預期的內部服務或 AI 生成錯誤。"},
    },
)
async def generate_diagrams(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮軟體專案。"),
) -> DiagramResponse:
    """接收 ZIP 上傳並產出 DiagramResponse（JSON）。"""
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info("[generate_diagrams] 收到圖表生成請求，檔案：%s", filename)
    zip_bytes: bytes = await file.read()
    return await _diagram_service.generate_diagrams(zip_bytes=zip_bytes, filename=filename)


@router.post(
    "/generate-and-download",
    status_code=status.HTTP_200_OK,
    summary="生成 Mermaid 圖表並下載 Markdown 檔案",
    description=(
        "上傳專案的 `.zip` 壓縮檔，生成完成後直接以 `.md` 附件回傳下載。\n\n"
        "下載的 Markdown 檔案包含 `graph TD` 架構圖與 `erDiagram`（若有 DB），\n"
        "用 ` ```mermaid ` 區塊包裝，可直接貼至 GitHub、Notion 或 mermaid.live 預覽。\n\n"
        "下載檔名格式：`{project_name}_diagrams.md`"
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"text/markdown": {}}, "description": "成功回傳 Markdown 圖表附件。"},
        413: {"model": ErrorResponse, "description": "超過上傳檔案大小限制。"},
        415: {"model": ErrorResponse, "description": "上傳非 .zip 格式之檔案。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP，或該專案內沒有找到適用的程式碼原始檔。"},
        500: {"model": ErrorResponse, "description": "非預期的內部服務或 AI 生成錯誤。"},
    },
)
async def generate_and_download(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮軟體專案。"),
) -> FileResponse:
    """接收 ZIP 上傳，生成圖表後以 Markdown 檔案形式回傳下載。

    Args:
        file: FastAPI 解析的 multipart 上傳檔案物件。

    Returns:
        以 ``FileResponse`` 包裝的 ``.md`` 附件，
        內含 Mermaid code fence，下載檔名格式為 ``{project_name}_diagrams.md``。

    Raises:
        UnsupportedFileTypeError: 非 .zip 格式。
    """
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info("[generate_and_download] 收到圖表下載請求，檔案：%s", filename)
    zip_bytes: bytes = await file.read()
    result = await _diagram_service.generate_diagrams(zip_bytes=zip_bytes, filename=filename)

    markdown_content = _render_mermaid_markdown(result)
    download_filename = f"{result.project_name}_diagrams.md"

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", encoding="utf-8", delete=False
    )
    try:
        tmp.write(markdown_content)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    logger.info("[generate_and_download] 回傳 '%s'（tmp=%s）", download_filename, tmp_path)
    return FileResponse(
        path=tmp_path,
        media_type="application/octet-stream",
        filename=download_filename,
    )
