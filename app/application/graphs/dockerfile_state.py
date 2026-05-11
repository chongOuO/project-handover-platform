"""Dockerfile 生成管線的 LangGraph State 定義。

DockerfileGraphState 是整條管線中各節點之間傳遞資料的唯一共享狀態容器。
使用 ``TypedDict`` 定義以確保型別安全並兼容 LangGraph 的狀態管理機制。
"""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class DockerfileGraphState(TypedDict, total=False):
    """Dockerfile AI 生成管線的全局共享狀態。

    每個節點可讀取任意欄位，並透過回傳更新後的字典來寫入欄位。
    使用 ``total=False`` 使所有欄位均為可選，允許節點在首次呼叫時
    只含有初始欄位，後續節點逐步填充狀態。

    Attributes:
        project_name: 被分析的專案名稱（由 Service 層在觸發前填入）。
        markdown_content: Phase 1 解析出的純文字原始碼文檔（作為輸入）。
        content_token_estimate: 對 markdown_content 的 Token 數估算。
        detected_language: detect_language_node 偵測到的主要語言（python / node / java / unknown）。
        detected_framework: detect_language_node 偵測到的框架（fastapi / express / spring / None）。
        base_image: detect_language_node 根據語言映射出的建議 base image。
        needs_build_stage: 是否需要 multi-stage build（Go / Java / Next.js 等需編譯的情境）。
        has_database: 是否偵測到資料庫相關依賴關鍵字。
        detected_db_type: 資料庫類型（postgresql / mysql / redis / mongodb）。
        dockerfile_content: generate_dockerfile_node 產出的 Dockerfile 文字。
        dockerignore_content: generate_dockerignore_node 產出的 .dockerignore 文字。
        compose_content: generate_compose_node 產出的 docker-compose.yml 文字。
        error: 任何節點拋出的錯誤訊息字串（供調試用）。
    """

    project_name: str
    markdown_content: str
    content_token_estimate: int
    detected_language: str
    detected_framework: Optional[str]
    base_image: str
    needs_build_stage: bool
    has_database: bool
    detected_db_type: Optional[str]
    dockerfile_content: str
    dockerignore_content: Optional[str]
    compose_content: str
    error: Optional[str]
