"""Dockerfile 生成 API 路由 (Dockerfile Router)。

提供兩個端點：
- ``POST /api/v1/dockerfile/generate``：回傳 JSON，包含 Dockerfile、
  .dockerignore 與 docker-compose.yml 文字內容。
- ``POST /api/v1/dockerfile/generate-and-download``：將三個生成檔案打包成
  ``.zip`` 壓縮包回傳下載（Dockerfile、.dockerignore、docker-compose.yml）。
"""

from __future__ import annotations

import logging
import tempfile
import zipfile

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.schemas.dockerfile_schema import DockerfileResponse
from app.api.schemas.response import ErrorResponse
from app.application.services.dockerfile_service import DockerfileService
from app.domain.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dockerfile", tags=["Dockerfile"])

# 模組層級執行個體 (Singleton)，應用啟動時建立，後續所有請求共用。
_dockerfile_service = DockerfileService()


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    summary="生成 Dockerfile / .dockerignore / docker-compose.yml（JSON）",
    description=(
        "上傳專案的 `.zip` 壓縮檔，回傳 AI 分析產生的 Docker 相關設定檔（JSON 格式）。\n\n"
        "流程：解壓縮 → 過濾 → Markdown 化 → 語言/框架/DB 偵測 → "
        "AI 生成 Dockerfile（含 multi-stage 判斷）→ AI 生成 .dockerignore → "
        "AI 生成 docker-compose.yml（含 DB service 偵測）。\n\n"
        "回傳純 JSON，包含 dockerfile_content、dockerignore_content、compose_content 三個文字欄位。"
    ),
    response_model=DockerfileResponse,
    responses={
        200: {"description": "成功產出 Dockerfile 相關設定。"},
        413: {"model": ErrorResponse, "description": "超過上傳檔案大小限制。"},
        415: {"model": ErrorResponse, "description": "上傳非 .zip 格式之檔案。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP，或該專案內沒有找到適用的程式碼原始檔。"},
        500: {"model": ErrorResponse, "description": "非預期的內部服務或 AI 生成錯誤。"},
    },
)
async def generate_dockerfile(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮軟體專案。"),
) -> DockerfileResponse:
    """接收 ZIP 上傳並產出 DockerfileResponse（JSON）。

    Args:
        file: FastAPI 解析的 multipart 上傳檔案物件。

    Returns:
        包含 dockerfile_content、dockerignore_content、compose_content 的 Pydantic 回應物件。

    Raises:
        UnsupportedFileTypeError: 上傳非 .zip 格式之檔案。
    """
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info("[generate_dockerfile] 收到 Dockerfile 生成請求，檔案：%s", filename)
    zip_bytes: bytes = await file.read()
    return await _dockerfile_service.generate_dockerfile(zip_bytes=zip_bytes, filename=filename)


@router.post(
    "/generate-and-download",
    status_code=status.HTTP_200_OK,
    summary="生成 Docker 設定檔並下載 ZIP 壓縮包",
    description=(
        "上傳專案的 `.zip` 壓縮檔，生成完成後將以下三個檔案打包成 `.zip` 回傳下載：\n\n"
        "- `Dockerfile`：可直接使用的 Docker 建置設定（含 multi-stage 判斷）\n"
        "- `.dockerignore`：依語言/框架產出的排除清單\n"
        "- `docker-compose.yml`：含 DB service 偵測的完整 Compose 設定\n\n"
        "下載檔名格式：`{project_name}_docker.zip`"
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"application/zip": {}}, "description": "成功回傳 Docker 設定檔 ZIP 壓縮包。"},
        413: {"model": ErrorResponse, "description": "超過上傳檔案大小限制。"},
        415: {"model": ErrorResponse, "description": "上傳非 .zip 格式之檔案。"},
        422: {"model": ErrorResponse, "description": "非有效 ZIP，或該專案內沒有找到適用的程式碼原始檔。"},
        500: {"model": ErrorResponse, "description": "非預期的內部服務或 AI 生成錯誤。"},
    },
)
async def generate_and_download(
    file: UploadFile = File(..., description="待分析的 ZIP 壓縮軟體專案。"),
) -> FileResponse:
    """接收 ZIP 上傳，生成三個 Docker 設定檔後以 ZIP 壓縮包回傳下載。

    ZIP 內包含：
    - ``Dockerfile``
    - ``.dockerignore``（若生成成功）
    - ``docker-compose.yml``

    Args:
        file: FastAPI 解析的 multipart 上傳檔案物件。

    Returns:
        以 ``FileResponse`` 包裝的 ``.zip`` 附件，
        下載檔名格式為 ``{project_name}_docker.zip``。

    Raises:
        UnsupportedFileTypeError: 非 .zip 格式。
    """
    filename: str = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise UnsupportedFileTypeError(filename=filename)

    logger.info("[generate_and_download] 收到 Docker 設定檔下載請求，檔案：%s", filename)
    zip_bytes: bytes = await file.read()
    result = await _dockerfile_service.generate_dockerfile(zip_bytes=zip_bytes, filename=filename)

    download_filename = f"{result.project_name}_docker.zip"

    # 將三個生成檔案打包成 ZIP
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Dockerfile", result.dockerfile_content)
            if result.dockerignore_content:
                zf.writestr(".dockerignore", result.dockerignore_content)
            zf.writestr("docker-compose.yml", result.compose_content)
        tmp_path = tmp.name
    finally:
        tmp.close()

    logger.info(
        "[generate_and_download] 回傳 '%s'（project=%s, tmp=%s）",
        download_filename,
        result.project_name,
        tmp_path,
    )
    return FileResponse(
        path=tmp_path,
        media_type="application/zip",
        filename=download_filename,
    )
