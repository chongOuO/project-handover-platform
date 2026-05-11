"""語言與框架偵測節點 (Detect Language Node)。

純函式節點，不呼叫 LLM，透過 keyword 掃描 markdown_content，
偵測專案的主要語言、框架、建議 base image、是否需要 multi-stage build
以及是否使用資料庫，將結果寫入 DockerfileGraphState。

設計理由：
    純 keyword 分析成本為零且速度快，適合用於「分流」資訊的準備節點。
    LLM 在後續節點只需依據這些已標準化的欄位進行生成，
    無需自己從海量原始碼文字中重複推斷語言類型。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.graphs.dockerfile_state import DockerfileGraphState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 語言偵測規則：(正則pattern, 語言標籤, base image, needs_build_stage)
# 規則依優先度排序，第一個命中即採用。
# ---------------------------------------------------------------------------
_LANGUAGE_RULES: list[tuple[str, str, str, bool]] = [
    # Go
    (r"\bgo\.mod\b|\bgo\.sum\b|\bpackage main\b", "go", "golang:1.22-alpine AS builder", True),
    # Java / Spring
    (r"\bpom\.xml\b|\bbuild\.gradle\b|\bspring\b", "java", "eclipse-temurin:21-jdk-alpine AS builder", True),
    # Node.js / Next.js
    (r"\bpackage\.json\b|\bnext\.config\b|\bnuxt\.config\b", "node", "node:20-alpine", False),
    # Python
    (r"\brequirements\.txt\b|\bpyproject\.toml\b|\bsetup\.py\b|\bPoetry\b|\bpipfile\b", "python", "python:3.11-slim", False),
    # Ruby
    (r"\bGemfile\b|\brails\b", "ruby", "ruby:3.3-slim", False),
    # PHP
    (r"\bcomposer\.json\b|\bartisan\b", "php", "php:8.3-fpm-alpine", False),
    # Rust
    (r"\bCargo\.toml\b|\bCargo\.lock\b", "rust", "rust:1.78-slim AS builder", True),
]

# ---------------------------------------------------------------------------
# 框架偵測規則：(pattern, 框架標籤)
# ---------------------------------------------------------------------------
_FRAMEWORK_RULES: list[tuple[str, str]] = [
    (r"\bfastapi\b", "fastapi"),
    (r"\bdjango\b", "django"),
    (r"\bflask\b", "flask"),
    (r"\bnestjs\b|\@nestjs\b", "nestjs"),
    (r"\bexpress\b", "express"),
    (r"\bnext\.js\b|\bnextjs\b|\bnext/", "nextjs"),
    (r"\bspring boot\b|\bspringboot\b", "spring-boot"),
    (r"\bgin\b", "gin"),
    (r"\becho\b", "echo"),
    (r"\bactix\b", "actix-web"),
]

# ---------------------------------------------------------------------------
# 資料庫偵測規則：(pattern, db_type)
# ---------------------------------------------------------------------------
_DB_RULES: list[tuple[str, str]] = [
    (r"\bpostgresql\b|\bpsycopg\b|\bpg\b|\bpostgres\b", "postgresql"),
    (r"\bmysql\b|\bmysqlclient\b|\bpymysql\b|\bdrizzle\b", "mysql"),
    (r"\bredis\b|\baioredis\b|\bcelery\b", "redis"),
    (r"\bmongodb\b|\bmotor\b|\bmongoose\b|\bpymongo\b", "mongodb"),
    (r"\bsqlite\b", "sqlite"),
]


def _detect_language(content: str) -> tuple[str, str, bool]:
    """依規則掃描 content 並回傳 (language, base_image, needs_build_stage)。"""
    lower = content.lower()
    for pattern, language, base_image, needs_build in _LANGUAGE_RULES:
        if re.search(pattern, lower, re.IGNORECASE):
            return language, base_image, needs_build
    return "unknown", "debian:bookworm-slim", False


def _detect_framework(content: str) -> str | None:
    """依規則掃描 content 並回傳框架標籤，無法偵測時回傳 None。"""
    for pattern, framework in _FRAMEWORK_RULES:
        if re.search(pattern, content, re.IGNORECASE):
            return framework
    return None


def _detect_database(content: str) -> tuple[bool, str | None]:
    """依規則掃描 content 並回傳 (has_database, db_type)。"""
    for pattern, db_type in _DB_RULES:
        if re.search(pattern, content, re.IGNORECASE):
            # sqlite 不需要獨立的 DB service container
            if db_type == "sqlite":
                return False, None
            return True, db_type
    return False, None


async def detect_language_node(state: DockerfileGraphState, config: Any) -> dict[str, Any]:
    """執行語言/框架/資料庫偵測的 LangGraph 節點（純函式，不呼叫 LLM）。

    從 ``markdown_content`` 中以 regex keyword 掃描各項特徵，
    將偵測結果寫入 State 供後續 LLM 節點使用。

    Args:
        state: Dockerfile Graph 的當前狀態。
        config: LangGraph 環境設定（此節點不使用）。

    Returns:
        包含 detected_language、detected_framework、base_image、
        needs_build_stage、has_database、detected_db_type 的更新字典。
    """
    logger.info("[detect_language_node] 開始語言/框架/資料庫偵測...")

    markdown_content: str = state.get("markdown_content", "")
    if not markdown_content:
        logger.warning("[detect_language_node] markdown_content 為空，使用 unknown fallback。")
        return {
            "detected_language": "unknown",
            "detected_framework": None,
            "base_image": "debian:bookworm-slim",
            "needs_build_stage": False,
            "has_database": False,
            "detected_db_type": None,
        }

    language, base_image, needs_build_stage = _detect_language(markdown_content)
    framework = _detect_framework(markdown_content)
    has_database, detected_db_type = _detect_database(markdown_content)

    logger.info(
        "[detect_language_node] 偵測結果 | 語言: %s | 框架: %s | base_image: %s | "
        "multi-stage: %s | DB: %s (%s)",
        language, framework, base_image, needs_build_stage, has_database, detected_db_type,
    )

    return {
        "detected_language": language,
        "detected_framework": framework,
        "base_image": base_image,
        "needs_build_stage": needs_build_stage,
        "has_database": has_database,
        "detected_db_type": detected_db_type,
    }
