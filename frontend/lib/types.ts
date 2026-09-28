export type Status =
  | "waiting"
  | "running"
  | "investigating"
  | "awaiting_approval"
  | "completed"
  | "completed_with_rejection"
  | "no_incident_observed"
  | "inconclusive"
  | "remediation_failed"
  | "cancelled"
  | "failed"
  | "pending"
  | "approved"
  | "rejected"
  | string;

export interface Finding {
  finding_id?: string;
  timestamp: string;
  source: string;
  message: string;
  raw_data: Record<string, unknown>;
}

export interface ToolCallAudit {
  tool_call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  status: string;
}

export interface LLMRun {
  run_id: string;
  agent: string;
  provider: "groq";
  model: string;
  status: "completed" | "failed" | string;
  attempts: number;
  input: {system_prompt: string; user_prompt: string};
  tool_calls: ToolCallAudit[];
  output: Record<string, unknown>;
  error?: string | null;
  started_at: string;
  completed_at: string;
  latency_ms: number;
  usage?: {input_tokens?: number; output_tokens?: number; total_tokens?: number};
}

export interface AgentState {
  investigation_id: string;
  agent_name: string;
  status: Status;
  findings: Finding[];
  steps: Array<{step: string}>;
  llm_runs?: LLMRun[];
  execution_mode?: "completed" | "failed" | string;
  started_at: string | null;
  completed_at: string | null;
}

export interface InvestigationQuestion {
  question_id: string;
  investigation_id: string;
  question: string;
  answer: string;
  citations: string[];
  insufficient_evidence: boolean;
  llm_run: LLMRun;
  created_at: string;
}

export interface Approval {
  evidence_version?: number;
  description?: string;
  approval_id: string;
  investigation_id: string;
  action_type: string;
  target: string;
  parameters?: Record<string, unknown>;
  supporting_finding_ids?: string[];
  supporting_observation_ids?: string[];
  expires_at?: string;
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
  evidence_version?: number;
  error?: string;
  investigation_id: string;
  incident_id: string;
  scenario: string;
  services?: string[];
  symptom?: string;
  lab_run_id?: string | null;
  assessment?: "incident_detected" | "no_incident_observed" | "insufficient_evidence" | null;
  recovery_origin?: string | null;
  status: Status;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  report_json: Partial<Report>;
  report_markdown: string;
  agents?: Record<string, AgentState>;
  approvals?: Approval[];
  questions?: InvestigationQuestion[];
}

export interface LabRun {
  run_id: string;
  scenario: string;
  status: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  fault: Record<string, unknown>;
  cleanup?: Record<string, unknown> | null;
  error?: string;
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
  run?: LLMRun;
}
