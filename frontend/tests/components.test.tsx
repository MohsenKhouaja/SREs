import {render, screen} from "@testing-library/react";
import {describe, expect, it} from "vitest";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";

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
