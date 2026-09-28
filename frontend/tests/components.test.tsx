import {cleanup, render, screen} from "@testing-library/react";
import {afterEach, describe, expect, it} from "vitest";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";
import {classifySystemStatus} from "@/components/app-shell";
import HomePage from "@/app/page";

afterEach(cleanup);

describe("shared product components", () => {
  it("treats a configured model and healthy dependencies as operational", () => {
    expect(classifySystemStatus({llm: "configured", loki: "healthy", prometheus: "healthy"})).toBe("operational");
    expect(classifySystemStatus({llm: "not_configured", loki: "healthy"})).toBe("partial");
  });

  it("renders status as readable text instead of color alone", () => {
    render(<Badge status="awaiting_approval" />);
    expect(screen.getByText("awaiting approval")).toBeInTheDocument();
  });

  it("uses a teaching empty state", () => {
    render(<Empty title="No investigations">Trigger a controlled failure.</Empty>);
    expect(screen.getByRole("heading", {name: "No investigations"})).toBeInTheDocument();
    expect(screen.getByText("Trigger a controlled failure.")).toBeInTheDocument();
  });
});

describe("landing page", () => {
  it("makes the incident lab and returning-operator paths explicit", () => {
    render(<HomePage />);
    expect(screen.getByText(/SREs is an evidence-first incident response platform/i)).toBeInTheDocument();
    expect(screen.getByRole("link", {name: /open the incident lab/i})).toHaveAttribute("href", "/lab");
    expect(screen.getAllByRole("link", {name: /open workspace|workspace/i})[0]).toHaveAttribute("href", "/investigations");
    expect(screen.getByText(/every suggested fix still needs human approval/i)).toBeInTheDocument();
  });

  it("explains the workflow without presenting invented incident outputs", () => {
    render(<HomePage />);
    expect(screen.getByText("Workflow guide")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("list", {name: /how investigation evidence is collected/i})).toBeInTheDocument();
    expect(screen.queryByText("Overall confidence")).not.toBeInTheDocument();
    expect(screen.queryByText(/INC-4821/)).not.toBeInTheDocument();
  });
});
