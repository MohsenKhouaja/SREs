import type {Approval} from "./types";

export const reportedStatuses = [
  "completed", "completed_with_rejection", "completed_with_expired_approval",
  "completed_with_invalidated_approval", "no_incident_observed", "inconclusive", "remediation_failed",
];

export function isTerminal(status?: string): boolean {
  return reportedStatuses.includes(status || "") || status === "failed" || status === "cancelled";
}

export function isApprovalOpen(approval: Approval, now = Date.now()): boolean {
  return approval.status === "pending" && (!approval.expires_at || Date.parse(approval.expires_at) > now);
}
