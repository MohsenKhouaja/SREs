export type Status =
  | "waiting"
  | "running"
  | "investigating"
  | "awaiting_approval"
  | "completed"
  | "completed_with_rejection"
  | "cancelled"
  | "failed"
  | "pending"
  | "approved"
  | "rejected"
  | string;

export interface Finding {
  timestamp: string;
  source: string;
  message: string;
  raw_data: Record<string, unknown>;
}

export interface AgentState {
  investigation_id: string;
  agent_name: string;
  status: Status;
  findings: Finding[];
  steps: Array<{step: string}>;
  started_at: string | null;
  completed_at: string | null;
}

export interface Approval {
  approval_id: string;
  investigation_id: string;
  action_type: string;
  target: string;
  reason: string;
  evidence: Record<string, unknown>;
  proposed_by: string;
  proposed_at: string;
  created_at: string;
  status: Status;
  decided_at: string | null;
}

export interface Report {
  summary: string;
  root_cause: string;
  evidence: Record<string, Finding[]>;
  recommendation: string;
  affected_services: string[];
  timeline: Array<{time: string; event: string; source?: string}>;
}

export interface Investigation {
  investigation_id: string;
  incident_id: string;
  scenario: string;
  status: Status;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  report_json: Partial<Report>;
  report_markdown: string;
  agents?: Record<string, AgentState>;
  approvals?: Approval[];
}

export interface StreamEvent {
  type: string;
  agent?: string;
  step?: string;
  status?: Status;
  findings?: Finding[];
  approval?: Approval;
  approval_id?: string;
  message?: string;
}
