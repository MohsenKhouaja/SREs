import type {HTMLAttributes} from "react";
import {clsx} from "clsx";

export function Panel({className, ...props}: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("panel", className)} {...props} />;
}
