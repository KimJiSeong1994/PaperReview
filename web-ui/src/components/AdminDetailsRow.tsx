import { useState } from 'react';
import type { ReactNode } from 'react';

const storageKey = (id: string) => `admin.dashboard.open.${id}`;

function readOpen(id: string): boolean {
  try {
    return localStorage.getItem(storageKey(id)) === '1';
  } catch {
    return false;
  }
}

/**
 * A collapsed dashboard row: the summary line carries the numbers, the body is
 * today's detail. Open state is remembered per row; the body mounts only while
 * open, so a closed row loads no chart.
 */
export default function AdminDetailsRow({ id, title, summary, children }: {
  id: string;
  title: string;
  summary: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => readOpen(id));
  return (
    <details
      className="admin-details-row"
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        setOpen(next);
        try {
          localStorage.setItem(storageKey(id), next ? '1' : '0');
        } catch {
          /* private mode: the row just forgets */
        }
      }}
    >
      <summary>
        <span className="admin-details-title">{title}</span>
        <span className="admin-details-summary">{summary}</span>
      </summary>
      {open && <div className="admin-details-body">{children}</div>}
    </details>
  );
}
