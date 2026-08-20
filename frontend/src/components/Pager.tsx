export function Pager({
  offset,
  limit,
  total,
  onPageChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onPageChange: (offset: number) => void;
}) {
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);

  return (
    <div className="pager">
      <button
        type="button"
        disabled={offset <= 0}
        onClick={() => onPageChange(Math.max(0, offset - limit))}
      >
        Prev
      </button>
      <span className="pager-status">
        Showing {start}-{end} of {total}
      </span>
      <button
        type="button"
        disabled={offset + limit >= total}
        onClick={() => onPageChange(offset + limit)}
      >
        Next
      </button>
    </div>
  );
}
