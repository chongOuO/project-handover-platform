"""LangGraph AI 分析管線的主圖定義 (Graph Builder)。

此模組建構並編譯整個 LangGraph ``StateGraph``，
串聯五個處理節點以形成從「讀取 Markdown」到「輸出兩份文件」的完整 AI 分析管線。

管線拓撲（DAG）：

    START
      │
    parse_markdown_node         ← 讀取 .md 來源文件
      │
    map_reduce_node             ← 大型專案 Map-Reduce 分批摘要（小型專案 passthrough）
      │
    ├─ generate_api_docs_node   ← 並行分支 1：生成 API 文件
    └─ generate_env_guide_node  ← 並行分支 2：生成環境指南
                │
           format_output_node   ← 匯合：組裝 AIReport 並寫出兩份文件
              │
             END
"""


from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.application.graphs.state import GraphState
from app.application.graphs.nodes.parse_markdown_node import parse_markdown_node
from app.application.graphs.nodes.map_reduce_node import map_reduce_node
from app.application.graphs.nodes.generate_api_docs_node import generate_api_docs_node
from app.application.graphs.nodes.generate_env_guide_node import generate_env_guide_node
from app.application.graphs.nodes.format_output_node import format_output_node

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """建構並編譯 AI 分析管線的 LangGraph StateGraph。

    **邏輯重點**：圖的拓撲採用「先串後分再合」的結構：
    - ``parse_markdown_node`` 是唯一的 I/O 入口，必須最先完成。
    - ``map_reduce_node`` 接於 parse 後：小型專案 passthrough，
      大型專案執行 Map-Reduce 分批摘要，確保下游節點收到完整資訊。
    - ``generate_api_docs_node`` 與 ``generate_env_guide_node`` 在概念上可並行
      （兩者都只依賴 ``markdown_content`` / ``map_reduce_summary``，互不依賴）。
    - ``format_output_node`` 作為最終匯合點。

    Returns:
        已編譯完成的 LangGraph 可執行圖實例。

    Example::

        graph = build_graph()
        result = await graph.ainvoke({
            "project_name": "my-project",
            "source_md_path": "/path/to/report.md",
            "output_dir": "/path/to/output",
        })
        print(result["api_docs_output_path"])
        print(result["env_guide_output_path"])
    """
    builder = StateGraph(GraphState)

    # ── 節點註冊 ──────────────────────────────────────────────────────────────
    builder.add_node("parse_markdown", parse_markdown_node)
    builder.add_node("map_reduce", map_reduce_node)
    builder.add_node("generate_api_docs", generate_api_docs_node)
    builder.add_node("generate_env_guide", generate_env_guide_node)
    builder.add_node("format_output", format_output_node)

    # ── 邊的連接（有向邊，定義執行順序）───────────────────────────────────────
    builder.add_edge(START, "parse_markdown")

    # parse_markdown 完成後進入 map_reduce 待機
    builder.add_edge("parse_markdown", "map_reduce")

    # map_reduce 完成後同時觸發兩個 AI 生成節點
    builder.add_edge("map_reduce", "generate_api_docs")
    builder.add_edge("map_reduce", "generate_env_guide")

    # 兩個生成節點完成後才進入最終輸出節點
    builder.add_edge("generate_api_docs", "format_output")
    builder.add_edge("generate_env_guide", "format_output")

    builder.add_edge("format_output", END)

    compiled = builder.compile()
    logger.info("AI 分析管線 StateGraph 編譯完成。")
    return compiled
