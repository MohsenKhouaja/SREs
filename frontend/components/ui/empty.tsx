import type {ReactNode} from "react";

export function Empty({title, children, action}: {title: string; children: ReactNode; action?: ReactNode}) {
  return <div className="empty-state"><div className="empty-mark" aria-hidden="true">◇</div><h2>{title}</h2><p>{children}</p>{action}</div>;
}
