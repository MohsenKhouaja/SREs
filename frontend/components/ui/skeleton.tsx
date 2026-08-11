export function Skeleton({rows = 4}: {rows?: number}) {
  return <div className="skeleton-stack" aria-label="Loading"><span className="sr-only">Loading</span>{Array.from({length: rows}, (_, index) => <span className="skeleton" key={index} />)}</div>;
}
