import {cleanup, render, screen} from "@testing-library/react";
import {afterEach, describe, expect, it} from "vitest";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";
import HomePage from "@/app/page";

afterEach(cleanup);

describe("shared product components", () => {
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
  it("makes the safe simulation and returning-operator paths explicit", () => {
    render(<HomePage />);
    expect(screen.getByRole("link", {name: /run a safe simulation/i})).toHaveAttribute("href", "/simulate");
    expect(screen.getAllByRole("link", {name: /open workspace|workspace/i})[0]).toHaveAttribute("href", "/investigations");
    expect(screen.getByText(/production actions always require an operator/i)).toBeInTheDocument();
  });

  it("frames the preview as static and explains the confidence provenance", () => {
    render(<HomePage />);
    expect(screen.getByText(/read-only preview/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("list", {name: /source-to-finding provenance/i})).toBeInTheDocument();
    expect(screen.getByText("Combined confidence")).toBeInTheDocument();
  });
});
