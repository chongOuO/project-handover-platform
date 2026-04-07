"""專案交接平台的 FastAPI 主體應用程式進入點。

開發環境下的啟動執行方式::

    .venv/bin/uvicorn main:app --reload --port 8000

成功伺服起來後即可透過瀏覽器前往 http://localhost:8000/docs 面板觀看並測試互動性質的 API OpenAPI 介面。
"""

from __future__ import annotations

import logging
from dotenv import load_dotenv

# 在應用程式最早期載入 .env，確保後續模組的 import 和初始化能讀到環境變數
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.exception_handler import register_exception_handlers
from app.api.routers.project_router import router as project_router
from app.api.routers.diagram_router import router as diagram_router

# ---------------------------------------------------------------------------
# 全域日誌配置 (Logging configuration)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 建置 FastAPI 執行實體本身
# ---------------------------------------------------------------------------

app = FastAPI(
    title="專案自動導讀及快速交接平台",
    description=(
        "這套自動化後台建置系統允許透過上傳一段具有原始碼架構的軟體開發目錄壓縮包 (Zipped files)。"
        "替開發團隊轉譯建構出一份具高可讀性，並適合作為內部新成員接手或文檔交接之精美 Markdown 自動導讀結構文件報告。\n\n"
        "**Phase 1 當前開發階段範圍**: 涵蓋完整「ZIP 解析上傳 → 雜訊源排除 (Smart filter) → 建構目錄與導讀樹結構區塊 (Directory tree) → 最後輸出包裝完成端文件 (Markdown report)」"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS 跨來源連線機制 — 在開發版階段暫予完全開放寬鬆環境；待實際上線專案需鎖緊該網域安全列表
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 註冊對接全域等級自訂異常攔截保護
# ---------------------------------------------------------------------------

register_exception_handlers(app)

# ---------------------------------------------------------------------------
# 掛載專屬路由功能群聚 (Routers)
# ---------------------------------------------------------------------------

app.include_router(project_router)
app.include_router(diagram_router)


# ---------------------------------------------------------------------------
# 基礎狀態確認的跟節點監控端 (Root health-check)
# ---------------------------------------------------------------------------


@app.get("/", tags=["Health"], summary="主機健康監聽狀態檢驗")
async def root() -> dict:
    """單純返回一個證明伺服主機已可連線的簡易包裝資訊。

    Returns:
        帶著 ``status`` 或一般 ``message`` 回覆欄位字樣之單純的 Python Dict 回應。
    """
    return {
        "status": "ok",
        "message": "專案交接平台的後端應用正在運作中。可先以訪問端造訪 /docs 路由以檢閱完整的 API 手冊指南喔！",
    }
