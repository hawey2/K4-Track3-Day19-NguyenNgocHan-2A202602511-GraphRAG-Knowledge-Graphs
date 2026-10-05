"""
Sufficient Context Agent — a LangGraph implementation of Google's agentic RAG loop.

Core idea (from Google Research, "Sufficient Context", ICLR 2025 + the June 2026
Gemini Enterprise Agent Platform agentic RAG framework):

    rewrite_query -> retrieve -> grade_sufficiency
                                      |
                  (insufficient + budget left) --> rewrite_query  (with feedback)
                  (sufficient OR out of budget) --> synthesize -> END

The Sufficient Context Agent is the `grade_sufficiency` node. Instead of just
answering, it inspects the query + retrieved snippets, decides SUFFICIENT vs
INSUFFICIENT, and — when insufficient — emits a *specific* "missing pieces" log
that becomes the feedback used to drive the next, more targeted search.

Dependencies:
    pip install langgraph langchain-core langchain-openai pydantic

Swap the LLM / retriever for your own (Gemini, Claude, vLLM Qwen, Milvus, etc.).
"""

from __future__ import annotations

import json
from typing import List, Literal, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI  # replace with your provider
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# 1. Plug in your own model + retriever here
# --------------------------------------------------------------------------- #

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Stand-in retriever. Replace `retrieve_docs` with a real call to Milvus /
# Vertex RAG Engine / your vector store. It just needs to map query -> chunks.
_FAKE_CORPUS = {
    "medications": "Discharge meds: Acetaminophen 500mg PRN, Aspirin 81mg daily.",
    "diet": "Nutrition notes: low-sodium diet, max 2g sodium per day.",
    "allergies": "Adverse events log: patient developed a rash from penicillin on day 2.",
}


def retrieve_docs(query: str, k: int = 2) -> List[Document]:
    """Toy keyword retriever — substitute your vector store .search() here."""
    q = query.lower()
    hits = [
        Document(page_content=text, metadata={"topic": topic})
        for topic, text in _FAKE_CORPUS.items()
        if topic in q or any(w in text.lower() for w in q.split())
    ]
    return hits[:k]


# --------------------------------------------------------------------------- #
# 2. Structured output for the Sufficient Context Agent
# --------------------------------------------------------------------------- #

class SufficiencyVerdict(BaseModel):
    """The Sufficient Context Agent's structured judgement."""
    status: Literal["SUFFICIENT", "INSUFFICIENT"] = Field(
        description="Whether the retrieved context can fully answer the query."
    )
    found: str = Field(description="What the snippets DO cover.")
    gap: str = Field(
        default="", description="What is missing. Empty if SUFFICIENT."
    )
    next_search: str = Field(
        default="",
        description="A targeted follow-up query to close the gap. Empty if SUFFICIENT.",
    )


# --------------------------------------------------------------------------- #
# 3. Graph state
# --------------------------------------------------------------------------- #

class RAGState(TypedDict):
    question: str           # original user question
    search_query: str       # current (possibly rewritten) search query
    docs: List[Document]    # accumulated retrieved chunks
    verdict: SufficiencyVerdict
    iterations: int
    max_iterations: int
    answer: str


# --------------------------------------------------------------------------- #
# 4. Nodes
# --------------------------------------------------------------------------- #

def rewrite_query(state: RAGState) -> dict:
    """Query Rewriter. First pass: use the question. Later passes: use the
    Sufficient Context Agent's `next_search` feedback to search more precisely."""
    verdict = state.get("verdict")
    if verdict and verdict.status == "INSUFFICIENT" and verdict.next_search:
        new_query = verdict.next_search
    else:
        new_query = state["question"]
    return {"search_query": new_query, "iterations": state["iterations"] + 1}


def retrieve(state: RAGState) -> dict:
    """RAG Agent. Retrieve and merge with what we already have (de-duplicated)."""
    new_docs = retrieve_docs(state["search_query"])
    seen = {d.page_content for d in state["docs"]}
    merged = state["docs"] + [d for d in new_docs if d.page_content not in seen]
    return {"docs": merged}


def grade_sufficiency(state: RAGState) -> dict:
    """THE SUFFICIENT CONTEXT AGENT.

    Reads the original question + accumulated snippets and decides whether the
    context is enough to answer. On INSUFFICIENT it must name the gap and propose
    a targeted next search (the 'missing pieces analysis')."""
    context = "\n".join(f"- {d.page_content}" for d in state["docs"]) or "(nothing retrieved)"

    grader = llm.with_structured_output(SufficiencyVerdict)
    verdict: SufficiencyVerdict = grader.invoke(
        [
            SystemMessage(content=(
                "You are a Sufficient Context Agent: a quality-control gate in a RAG "
                "pipeline. Decide whether the RETRIEVED CONTEXT contains everything "
                "needed to fully and correctly answer the QUESTION. If the question "
                "asks for multiple things, ALL must be covered to be SUFFICIENT. "
                "When INSUFFICIENT, state exactly what is missing and propose a single "
                "targeted follow-up search query to find it."
            )),
            HumanMessage(content=(
                f"QUESTION:\n{state['question']}\n\n"
                f"RETRIEVED CONTEXT:\n{context}"
            )),
        ]
    )
    return {"verdict": verdict}


def synthesize(state: RAGState) -> dict:
    """Synthesis Agent. Writes the grounded final answer from accumulated context."""
    context = "\n".join(f"- {d.page_content}" for d in state["docs"])
    resp = llm.invoke(
        [
            SystemMessage(content=(
                "Answer the question using ONLY the provided context. Be precise and "
                "grounded. If something is genuinely absent, say so explicitly."
            )),
            HumanMessage(content=f"QUESTION:\n{state['question']}\n\nCONTEXT:\n{context}"),
        ]
    )
    return {"answer": resp.content}


# --------------------------------------------------------------------------- #
# 5. Conditional edge: iterate or stop (the 'persistence' that defines this loop)
# --------------------------------------------------------------------------- #

def route_after_grading(state: RAGState) -> Literal["rewrite_query", "synthesize"]:
    v = state["verdict"]
    out_of_budget = state["iterations"] >= state["max_iterations"]
    if v.status == "SUFFICIENT" or out_of_budget:
        return "synthesize"
    return "rewrite_query"  # loop back with the gap-closing feedback


# --------------------------------------------------------------------------- #
# 6. Build the graph
# --------------------------------------------------------------------------- #

def build_graph():
    g = StateGraph(RAGState)
    g.add_node("rewrite_query", rewrite_query)
    g.add_node("retrieve", retrieve)
    g.add_node("grade_sufficiency", grade_sufficiency)
    g.add_node("synthesize", synthesize)

    g.set_entry_point("rewrite_query")
    g.add_edge("rewrite_query", "retrieve")
    g.add_edge("retrieve", "grade_sufficiency")
    g.add_conditional_edges("grade_sufficiency", route_after_grading)
    g.add_edge("synthesize", END)
    return g.compile()


# --------------------------------------------------------------------------- #
# 7. Run
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app = build_graph()
    result = app.invoke(
        {
            "question": (
                "What are John Doe's discharge medications, dietary restrictions, "
                "and did he have any allergic reactions during his stay?"
            ),
            "search_query": "",
            "docs": [],
            "iterations": 0,
            "max_iterations": 3,
            "answer": "",
        }
    )
    print("Iterations used:", result["iterations"])
    print("Final verdict:", result["verdict"].status)
    print("\nANSWER:\n", result["answer"])
