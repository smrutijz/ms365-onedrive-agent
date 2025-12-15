from langgraph import Node, Graph, run_graph
from pydantic import BaseModel
from typing import List, Optional, Literal
from src.clients.graph_api import GraphClient

# -----------------------
# Models
# -----------------------

class Candidate(BaseModel):
    id: str
    name: str
    type: Literal["folder", "file"]
    mime_type: Optional[str]

class DecisionStep(BaseModel):
    attempt: int
    depth: int
    chosen_id: str
    chosen_name: str
    chosen_type: str
    reason: str
    alternatives: List[str]

class FoundFile(BaseModel):
    id: str
    name: str
    path: str
    content_md: Optional[str]

class RejectedPath(BaseModel):
    path: str
    file_name: str
    rejection_reason: str

class AgentState(BaseModel):
    user_query: str
    drive_description: Optional[str] = None
    max_attempts: int = 3
    start_item_id: Optional[str] = None
    current_item_id: Optional[str] = None
    current_path: str = ""
    depth: int = 0
    attempt: int = 1
    done: bool = False
    visited_items: set = set()
    rejected_paths: List[RejectedPath] = []
    candidates: List[Candidate] = []
    decision_trace: List[DecisionStep] = []
    current_file: Optional[FoundFile] = None
    verified: bool = False


# -----------------------
# LangGraph Nodes
# -----------------------

def resolve_start(state: AgentState, graph_client: GraphClient):
    if state.start_item_id:
        state.current_item_id = state.start_item_id
    elif state.current_path:
        state.start_item_id = graph_client.get_folder_id_by_path(state.current_path)
        state.current_item_id = state.start_item_id
    else:
        state.current_item_id = "root"
    return state

def list_children(state: AgentState, graph_client: GraphClient):
    if state.current_item_id == "root":
        data = graph_client.list_root()
    else:
        data = graph_client.list_folder(state.current_item_id)
    state.candidates = [
        Candidate(
            id=item["id"],
            name=item["name"],
            type="folder" if item.get("folder") else "file",
            mime_type=item.get("file", {}).get("mimeType")
        )
        for item in data.get("value", [])
    ]
    return state

def decide_next(state: AgentState, llm_tool):
    if not state.candidates:
        state.done = True
        return state

    # Prepare LLM input
    llm_input = {
        "user_query": state.user_query,
        "drive_description": state.drive_description,
        "current_path": state.current_path,
        "candidates": [c.dict() for c in state.candidates],
        "rejected_paths": [r.dict() for r in state.rejected_paths],
        "attempt": state.attempt,
        "depth": state.depth
    }

    # Call LLM (external tool or OpenAI) to decide next item
    llm_response = llm_tool.decide_next(llm_input)

    # Example LLM response:
    # {
    #   "action": "select_file" or "enter_folder",
    #   "id": "item-id",
    #   "name": "Item Name",
    #   "reason": "LLM explanation why this is most relevant"
    # }

    chosen_id = llm_response["id"]
    chosen_name = llm_response["name"]
    action = llm_response["action"]
    reason = llm_response["reason"]

    # Save decision trace
    state.decision_trace.append(
        DecisionStep(
            attempt=state.attempt,
            depth=state.depth,
            chosen_id=chosen_id,
            chosen_name=chosen_name,
            chosen_type="file" if action == "select_file" else "folder",
            reason=reason,
            alternatives=[c.name for c in state.candidates if c.id != chosen_id]
        )
    )

    # Execute action
    if action == "select_file":
        state.current_file = FoundFile(id=chosen_id, name=chosen_name, path=state.current_path + "/" + chosen_name)
        state.done = True
    elif action == "enter_folder":
        state.current_item_id = chosen_id
        state.current_path += "/" + chosen_name
        state.depth += 1

    return state


def download_and_verify(state: AgentState, graph_client: GraphClient):
    if state.current_file:
        file_bytes = graph_client.download_file(state.current_file.id)
        # Placeholder Dockling: convert to markdown string
        md_text = file_bytes.decode("utf-8", errors="ignore")  # In practice, call Dockling API
        state.current_file.content_md = md_text

        # --- Placeholder verification ---
        # You can replace with LLM semantic match
        if "resume" in md_text.lower():
            state.verified = True
        else:
            state.verified = False
            state.rejected_paths.append(
                RejectedPath(
                    path=state.current_path,
                    file_name=state.current_file.name,
                    rejection_reason="Content did not match query"
                )
            )
            state.current_file = None
            state.attempt += 1
            state.done = state.attempt > state.max_attempts
            # Reset traversal if not done
            if not state.done:
                state.current_item_id = state.start_item_id
                state.current_path = ""
                state.depth = 0

    return state

# -----------------------
# Assemble Graph
# -----------------------

def build_agent_graph(state: AgentState, graph_client: GraphClient):
    g = Graph()
    
    g.add_node(Node(func=resolve_start, name="Resolve Start", inputs={"state": state, "graph_client": graph_client}))
    g.add_node(Node(func=list_children, name="List Children", inputs={"state": state, "graph_client": graph_client}))
    g.add_node(Node(func=decide_next, name="Decide Next", inputs={"state": state}))
    g.add_node(Node(func=download_and_verify, name="Download & Verify", inputs={"state": state, "graph_client": graph_client}))
    
    # Edges in linear flow
    g.add_edge("Resolve Start", "List Children")
    g.add_edge("List Children", "Decide Next")
    g.add_edge("Decide Next", "List Children", condition=lambda s: not s.done)  # loop until done
    g.add_edge("Decide Next", "Download & Verify", condition=lambda s: s.done)
    
    return g

# -----------------------
# Run Example
# -----------------------

# access_token = "<YOUR_TOKEN>"
# graph_client = GraphClient(access_token)
# state = AgentState(user_query="find my resume, which i blv in pdf format", start_item_id=None, drive_description="Files organized by Work, Personal, Education")

# g = build_agent_graph(state, graph_client)
# final_state = run_graph(g)
# print(final_state.current_file)
# print([d.dict() for d in final_state.decision_trace])
