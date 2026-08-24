export type PathNodeStatus = "locked" | "current" | "completed" | "skipped";

export interface LearningPathNode {
  path_node_id: string;
  knowledge_id: string;
  title: string;
  path_order: number;
  status: PathNodeStatus;
  completed_at?: string | null;
  completion_evidence_ids: string[];
  completion_condition: { type: string; threshold: number };
  resource_state?: "not_generated" | "generating" | "ready" | "failed";
  resource_task_id?: string | null;
}
export interface LearningPathState {
  path_id: string;
  current_node_id?: string | null;
  revision_summary?: {
    type: "prerequisite_inserted";
    message: string;
    inserted_knowledge_ids: string[];
    previous_current_node_id?: string | null;
    current_node_id?: string | null;
  } | null;
  nodes: LearningPathNode[];
  stages: Array<{
    name: string;
    description?: string;
    knowledge_ids?: string[];
  }>;
}
