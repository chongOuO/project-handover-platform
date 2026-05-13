# 專案交接平台 (Project Handover Platform)

## 1. 專案概述
本專案為一套基於 FastAPI 建構的自動化後端平台，旨在解決軟體開發團隊在專案交接與文件撰寫上所耗費的時間成本。系統接受完整軟體開發目錄之壓縮檔 (ZIP)，透過內部工作流解析原始碼，並自動排除雜訊檔案，最終轉譯為具備高度可讀性之 Markdown 導讀文件。

目前系統涵蓋四大核心模組：
1. **專案解析與報告生成 (Project Report)**：上傳並解析 ZIP 檔案，產生目錄導讀結構與 Markdown 報告。
2. **架構圖表生成 (Diagram Generation)**：針對特定程式碼邏輯，動態生成相對應之 Mermaid 架構圖。
3. **部署配置生成 (Docker Configuration)**：自動分析專案技術棧，並生成對應的 Dockerfile 與 docker-compose.yml。
4. **專案互動問答 (Q&A Workflow)**：提供基於專案原始碼的上下文問答功能，並具備 Session 狀態管理機制。

## 2. 系統架構與技術棧

### 2.1 核心框架與語言
* **後端框架**：FastAPI (Python 3.10+)
* **非同步伺服器**：Uvicorn
* **資料驗證與設定**：Pydantic 與 Pydantic Settings

### 2.2 架構設計模式 (Clean Architecture)
本專案嚴格遵守 Clean Architecture 分層設計原則，確保各層職責分離與高可測試性：
* **Router (API 路由層)**：負責接收 HTTP 請求、驗證輸入參數，並透過依賴注入 (Dependency Injection) 呼叫對應的 Service 層。
* **Service (業務邏輯層)**：封裝核心業務邏輯與流程編排 (包含 LangGraph 之調用)，不直接依賴外部網路框架。
* **Repository (資料存取層 / 基礎設施層)**：負責與外部系統 (例如 InMemorySessionStore、檔案系統、LLM API) 進行資料存取與狀態維護。

### 2.3 LLM 與工作流編排
* **LangGraph**：負責調度複雜的多節點邏輯 (例如 Map-Reduce 程式碼總結機制)。Graph 的 State 皆以 Pydantic Model 進行嚴格型別定義，並於各節點實作容錯與重試機制。
* **LangChain**：整合 OpenAI 與 Google Gemini 等語言模型，進行程式碼摘要與語意理解。

## 3. 開發與環境設置

### 3.1 環境變數設定
專案根目錄下需配置 `.env` 檔案以載入環境變數。請參考 `.env.example` 建立配置：

```bash
cp .env.example .env
```

必要參數包含：
* LLM API Keys (例如 `OPENAI_API_KEY`、`GOOGLE_API_KEY`)
* 伺服器配置與環境切換參數

### 3.2 虛擬環境與套件安裝
建議使用 `venv` 建立獨立虛擬環境，並安裝必要依賴：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```



### 3.3 啟動伺服器
請於專案根目錄執行以下指令啟動開發伺服器：

```bash
uvicorn main:app --reload --port 8000
```

伺服器啟動後，請前往 [http://localhost:8000/docs](http://localhost:8000/docs) 檢視 OpenAPI (Swagger UI) API 互動面板。

## 4. 模組設計細節與規範

### 4.1 全域異常處理與日誌 (Global Exception & Logging)
* **Exception Handler**：透過統一註冊之中介軟體攔截並格式化例外回應，避免底層錯誤堆疊外露至前端。
* **結構化日誌**：全面導入標準 `logging` 模組，並於 LangGraph 節點與核心業務流程中寫入追蹤日誌，以利異常排查。

### 4.2 Session 管理與並行控制
* **記憶體儲存 (InMemorySessionStore)**：Q&A 模組採用記憶體儲存 Session，並透過 FastAPI 的 `lifespan` 事件啟動背景非同步任務 (`asyncio.Task`) 進行過期 Session 之定期清理。
* **非同步優先 (Async-First)**：所有檔案 I/O 解析與外部 LLM 請求皆全面使用 `async/await`，確保高併發情境下維持系統吞吐量。

