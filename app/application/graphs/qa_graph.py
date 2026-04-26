"""Q&A LangGraph 管線的主圖定義。

管線拓撲（線性 DAG）：

    START
      │
    classify_question   ← 分類問題類型 + 提取關鍵字（LLM 小型 Prompt）
      │
    retrieve_context    ← 純記憶體關鍵字匹配，篩選相關程式碼片段
      │
    generate_answer     ← 組裝完整 Prompt，呼叫 LLM 生成答案
      │
    END
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.application.graphs.qa_state import QAGraphState
from app.application.graphs.qa_nodes.classify_question_node import classify_question_node
from app.application.graphs.qa_nodes.retrieve_context_node import retrieve_context_node
from app.application.graphs.qa_nodes.generate_answer_node import generate_answer_node

logger = logging.getLogger(__name__)


def build_qa_graph() -> StateGraph:
    """建構並編譯 Q&A 管線的 LangGraph StateGraph。

    Returns:
        已編譯完成的 LangGraph 可執行圖實例。

    Example::

        graph = build_qa_graph()
        result = await graph.ainvoke({
            "question": "這個專案的認證機制是什麼？",
            "project_files_json": "...",
            "markdown_content": "...",
            "map_reduce_summary": None,
        })
        print(result["answer"])
    """
    builder = StateGraph(QAGraphState)

    builder.add_node("classify_question", classify_question_node)
    builder.add_node("retrieve_context", retrieve_context_node)
    builder.add_node("generate_answer", generate_answer_node)

    builder.add_edge(START, "classify_question")
    builder.add_edge("classify_question", "retrieve_context")
    builder.add_edge("retrieve_context", "generate_answer")
    builder.add_edge("generate_answer", END)

    compiled = builder.compile()
    logger.info("Q&A LangGraph 管線編譯完成。")
    return compiled
