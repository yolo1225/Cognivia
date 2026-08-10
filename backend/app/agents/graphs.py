from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.v2_nodes import (
    V2_GRAPH_STATE,
    V2Runtime,
    build_nodes,
    route_after_finalize,
    route_after_human_review,
    route_after_prepare,
    route_after_profile,
)


def build_learning_graph(
    node_overrides: dict[str, Any] | None = None,
    checkpointer: Any | None = None,
    runtime: V2Runtime | None = None,
):
    """Build the single V2 top-level graph for initial and feedback tasks."""

    owned_runtime = runtime is None
    active_runtime = runtime or V2Runtime.production()
    node_map = build_nodes(active_runtime)
    node_map.update(node_overrides or {})

    graph = StateGraph(V2_GRAPH_STATE)
    graph_node = {name: f"{name}_node" for name in node_map}
    for name, func in node_map.items():
        # V2 State owns fields named prepare_task, analyze_profile, etc.;
        # LangGraph reserves those channel names, so internal node IDs differ.
        graph.add_node(graph_node[name], func)

    graph.add_edge(START, graph_node["prepare_task"])
    graph.add_conditional_edges(
        graph_node["prepare_task"],
        route_after_prepare,
        {
            "interpret_feedback": graph_node["interpret_feedback"],
            "analyze_profile": graph_node["analyze_profile"],
            "human_review": graph_node["human_review"],
        },
    )
    graph.add_edge(graph_node["interpret_feedback"], graph_node["analyze_profile"])
    graph.add_conditional_edges(
        graph_node["analyze_profile"],
        route_after_profile,
        {
            "retrieve_knowledge": graph_node["retrieve_knowledge"],
            "finalize_task": graph_node["finalize_task"],
        },
    )
    graph.add_edge(graph_node["retrieve_knowledge"], graph_node["generate_resource"])
    graph.add_edge(graph_node["generate_resource"], graph_node["review_resource"])
    graph.add_edge(graph_node["review_resource"], graph_node["finalize_task"])
    graph.add_conditional_edges(
        graph_node["finalize_task"],
        route_after_finalize,
        {
            "retrieve_knowledge": graph_node["retrieve_knowledge"],
            "human_review": graph_node["human_review"],
            "end": END,
        },
    )
    graph.add_conditional_edges(
        graph_node["human_review"],
        route_after_human_review,
        {
            "retrieve_knowledge": graph_node["retrieve_knowledge"],
            "finalize_task": graph_node["finalize_task"],
            "end": END,
        },
    )
    compiled = graph.compile(checkpointer=checkpointer)
    # A caller supplying a runtime owns its lifecycle. The default runtime is
    # retained by the compiled graph so the retrieval client stays alive.
    if owned_runtime:
        setattr(compiled, "_v2_runtime", active_runtime)
    return compiled
