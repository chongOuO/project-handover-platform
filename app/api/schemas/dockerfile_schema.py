"""Dockerfile 生成功能的 API Schema 定義。

定義請求/回應的 Pydantic 資料模型，供 Router 與 Service 層共用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class DockerfileResponse(BaseModel):
    """Dockerfile 生成結果的回應模型。

    Attributes:
        project_name: 被分析的專案名稱。
        language: 偵測到的主要程式語言（例如 python、node、java）。
        framework: 偵測到的框架（例如 fastapi、express、spring）；未偵測到則為 None。
        base_image: LLM 選用的 Docker base image（例如 python:3.11-slim）。
        has_database: 是否偵測到資料庫相關依賴。
        detected_db_type: 資料庫類型（postgresql / mysql / redis / mongodb）；無則為 None。
        dockerfile_content: 生成的完整 Dockerfile 文字內容。
        dockerignore_content: 生成的 .dockerignore 文字內容；無則為 None。
        compose_content: 生成的 docker-compose.yml 文字內容。
        generated_at: 生成時間戳（UTC）。
    """

    project_name: str = Field(..., description="被分析的專案名稱。")
    language: str = Field(..., description="偵測到的主要程式語言，例如 python、node、java。")
    framework: Optional[str] = Field(None, description="偵測到的框架，例如 fastapi、express。")
    base_image: str = Field(..., description="選用的 Docker base image，例如 python:3.11-slim。")
    has_database: bool = Field(False, description="是否偵測到資料庫相關依賴。")
    detected_db_type: Optional[str] = Field(
        None, description="資料庫類型，例如 postgresql、mysql、redis。"
    )
    dockerfile_content: str = Field(..., description="生成的完整 Dockerfile 文字。")
    dockerignore_content: Optional[str] = Field(
        None, description="生成的 .dockerignore 文字。"
    )
    compose_content: str = Field(..., description="生成的 docker-compose.yml 文字。")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="生成時間戳（UTC）。",
    )
