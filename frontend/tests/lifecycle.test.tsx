import {cleanup, render, screen} from "@testing-library/react";
import {afterEach, describe, expect, it, vi} from "vitest";
import type {Approval, Investigation} from "@/lib/types";
import {isApprovalOpen, isTerminal} from "@/lib/investigation-state";

const state = vi.hoisted(() => ({investigation: undefined as Investigation | undefined, approval: undefined as Approval | undefined}));
vi.mock("next/navigation", () => ({useParams: () => ({id: "test"}), useRouter: () => ({push: vi.fn()})}));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  useInvestigation: () => ({data: state.investigation}),
  useApproval: () => ({data: state.approval}),
  useLabRun: () => ({data: undefined}),
}));
vi.mock("@/lib/use-stream", () => ({useInvestigationStream: vi.fn(() => ({events: [], connected: false}))}));
import InvestigationPage from "@/app/investigation/[id]/page";
import ApprovalPage from "@/app/approvals/[id]/page";
import ReportPage from "@/app/investigation/[id]/report/page";
import {useInvestigationStream} from "@/lib/use-stream";

afterEach(cleanup);

function investigation(status: string): Investigation {
  return {incident_id: "test", investigation_id: "test", scenario: "redis-unavailable", status, evidence_version: 3, agents: {}, approvals: [], report_json: {}, report_markdown: ""} as unknown as Investigation;
}

describe("report lifecycle", () => {
  it("labels a paused report as waiting for approval, not running", () => {
    state.investigation = investigation("awaiting_approval");
    render(<InvestigationPage />);
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
  });

  it("closes the stream and exposes the report on expiry completion", () => {
    state.investigation = investigation("completed_with_expired_approval");
    render(<InvestigationPage />);
    expect(screen.getByText("Closed")).toBeInTheDocument();
    expect(screen.getByRole("link", {name: "View report"})).toBeInTheDocument();
    expect(useInvestigationStream).toHaveBeenLastCalledWith("test", false);
  });

  it("removes decision controls even if an expired approval still says pending", () => {
    state.approval = {approval_id: "approval", investigation_id: "test", action_type: "start_service", status: "pending", expires_at: "2020-01-01T00:00:00Z", evidence_version: 3, evidence: {}} as Approval;
    render(<ApprovalPage />);
    expect(screen.queryByRole("button", {name: "Approve operation"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Reject"})).not.toBeInTheDocument();
    expect(screen.getByText(/No operation can be executed/)).toBeInTheDocument();
  });

  it("does not tell operators a failed report is still being generated", () => {
    state.investigation = {...investigation("failed"), error: "Groq unavailable"};
    render(<ReportPage />);
    expect(screen.getByText(/No report was produced.*Groq unavailable/)).toBeInTheDocument();
  });

  it("recognizes terminal outcomes and deadlines", () => {
    expect(isTerminal("completed_with_invalidated_approval")).toBe(true);
    expect(isTerminal("reporting")).toBe(false);
    expect(isApprovalOpen({status: "pending", expires_at: "2026-01-01T00:00:00Z"} as Approval, Date.parse("2026-01-01T00:00:00Z"))).toBe(false);
  });
});
