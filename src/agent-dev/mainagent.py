import os
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field

from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

# ---------------------------------------------------------
# 1. PYDANTIC MODELS (STATE & HISTORY)
# ---------------------------------------------------------
class RerankItem(BaseModel):
    item_id: str
    name: str
    score: float = Field(description="Score between 0.0 and 1.0")
    explanation: str

class SearchParams(BaseModel):
    query_string: str
    query_template: str
    semantic_query: Optional[str] = None
    explanation: str

class AgentHistory(BaseModel):
    iteration: int
    stage: Literal["query", "search", "rerank", "select"]
    query_string: Optional[str] = None
    result_count: Optional[int] = None
    explanation: Optional[str] = None

class AgentState(BaseModel):
    user_query: str
    system_prompt: str
    iteration: int = 0
    search_params: Optional[SearchParams] = None
    search_results: List[Dict[str, Any]] = []
    ranked_items: List[RerankItem] = []
    history: List[AgentHistory] = []
    final_output: Optional[Dict[str, Any]] = None

# ---------------------------------------------------------
# 2. NODES (AGENT LOGIC)
# ---------------------------------------------------------

def generate_query_node(state: AgentState, config):
    """Generates KQL search parameters based on the system prompt and user intent."""
    # In a real scenario, use Trustcall or LLM structured output here
    # Mocking the KQL generation logic for brevity
    new_iteration = state.iteration + 1
    
    # Logic to handle Product Mapping (e.g., MOC -> Cargo) should be here
    # This uses the sp_helper_client passed via config
    
    params = SearchParams(
        query_string="HWA",
        query_template="path:tenant.sharepoint.com AND contenttype:folder",
        explanation="Detected request for folder related to HWA for 2025."
    )
    
    return {
        "search_params": params,
        "iteration": new_iteration,
        "history": state.history + [AgentHistory(iteration=new_iteration, stage="query", query_string=params.query_string)]
    }

def execute_search_node(state: AgentState, config):
    """Executes the search using the GraphAPI helper."""
    sp_helper = config["configurable"].get("sp_helper_client")
    # results = sp_helper.search(state.search_params)
    mock_results = [{"id": "123", "name": "HWA_Renewals_2025"}]
    
    return {
        "search_results": mock_results,
        "history": state.history + [AgentHistory(iteration=state.iteration, stage="search", result_count=len(mock_results))]
    }

def rerank_node(state: AgentState):
    """Reranks results using an LLM to find the best match."""
    ranked = [RerankItem(item_id="123", name="HWA_Renewals_2025", score=0.95, explanation="Exact match")]
    return {
        "ranked_items": ranked,
        "history": state.history + [AgentHistory(iteration=state.iteration, stage="rerank", explanation="Found high confidence match")]
    }

def select_final_node(state: AgentState):
    """Formats the final output for the user."""
    return {
        "final_output": {
            "top_result": state.ranked_items[0] if state.ranked_items else None,
            "iterations": state.iteration
        }
    }

# ---------------------------------------------------------
# 3. ROUTING LOGIC
# ---------------------------------------------------------
def should_continue(state: AgentState):
    # If no results found or score is too low, loop back to refine
    if not state.ranked_items or state.ranked_items[0].score < 0.8:
        if state.iteration < 3: # Max retries
            return "refine"
    return "end"

# ---------------------------------------------------------
# 4. BUILD THE GRAPH
# ---------------------------------------------------------
def build_graph(checkpointer=None, store=None):
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("generate_query", generate_query_node)
    workflow.add_node("execute_search", execute_search_node)
    workflow.add_node("rerank", rerank_node)
    workflow.add_node("select", select_final_node)

    # Set Edges
    workflow.add_edge(START, "generate_query")
    workflow.add_edge("generate_query", "execute_search")
    workflow.add_edge("execute_search", "rerank")
    
    # Conditional Routing
    workflow.add_conditional_edges(
        "rerank",
        should_continue,
        {
            "refine": "generate_query",
            "end": "select"
        }
    )
    
    workflow.add_edge("select", END)

    return workflow.compile(checkpointer=checkpointer, store=store)

# ---------------------------------------------------------
# 5. VISUALIZATION (RESTRICTED ENVIRONMENT FIX)
# ---------------------------------------------------------
def visualize_graph(graph):
    """Safe visualization for 2026 Restricted Environments."""
    print("\n--- MERMAID SYNTAX (Paste into mermaid.live) ---")
    mermaid_code = graph.get_graph().draw_mermaid()
    print(mermaid_code)
    
    print("\n--- ASCII REPRESENTATION ---")
    try:
        print(graph.get_graph().draw_ascii())
    except ImportError:
        print("Note: Install 'grandalf' for ASCII tree visualization.")

# ---------------------------------------------------------
# EXECUTION
# ---------------------------------------------------------
if __name__ == "__main__":
    checkpointer = MemorySaver()
    app = build_graph(checkpointer=checkpointer)
    
    # Visualize
    visualize_graph(app)
