import type {ReactNode} from "react";
import {clsx} from "clsx";
import type {Status} from "@/lib/types";

export function Badge({status, children}: {status: Status; children?: ReactNode}) {
  return <span className={clsx("badge", `status-${status.replaceAll("_", "-")}`)}><span aria-hidden="true" className="status-dot" />{children ?? status.replaceAll("_", " ")}</span>;
}
