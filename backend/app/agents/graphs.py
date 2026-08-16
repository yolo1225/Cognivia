from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    GRAPH_STATE,
    AgentRuntime,
    build_nodes,
    route_after_finalize,
    route_after_prepare,
    route_after_profile,
)


def build_learning_graph(
    node_overrides: dict[str, Any] | None = None,
    checkpointer: Any | None = None,
    runtime: AgentRuntime | None = None,
):
    """Build the single V4 graph with automatic revision and atomic publication."""

    owned_runtime = runtime is None
    active_runtime = runtime or AgentRuntime.production()
    node_map = build_nodes(active_runtime)
    node_map.update(node_overrides or {})

    graph = StateGraph(GRAPH_STATE)
    graph_node = {name: f"{name}_node" for name in node_map}
    for name, func in node_map.items():
        # V3 State owns fields named prepare_task, analyze_profile, etc.;
        # LangGraph reserves those channel names, so internal node IDs differ.
        graph.add_node(graph_node[name], func)

    graph.add_edge(START, graph_node["prepare_task"])
    graph.add_conditional_edges(
        graph_node["prepare_task"],
        route_after_prepare,
        {
            "interpret_feedback": graph_node["interpret_feedback"],
            "analyze_profile": graph_node["analyze_profile"],
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
            "end": END,
        },
    )
    compiled = graph.compile(checkpointer=checkpointer)
    # A caller supplying a runtime owns its lifecycle. The default runtime is
    # retained by the compiled graph so the retrieval client stays alive.
    if owned_runtime:
        setattr(compiled, "_agent_runtime", active_runtime)
    return compiled
