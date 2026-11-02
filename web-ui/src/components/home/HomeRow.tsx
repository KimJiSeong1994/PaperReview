import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

// One stroke set for every row's leading slot (16px grid).
const ICON_PATH = {
  compare: 'M3 5.5h9.5M10 3l2.5 2.5L10 8M13 10.5H3.5M6 8l-2.5 2.5L6 13',
  review: 'M4 1.75h5.25L12.5 5v9.25H4zM9 1.75v3.5h3.5M6.25 10l1.25 1.25L10 8.75',
  course: 'M2.5 5.5 8 3l5.5 2.5L8 8zM2.5 8.5 8 11l5.5-2.5M2.5 11.5 8 14l5.5-2.5',
  search: 'M7 2.75a4.25 4.25 0 1 0 0 8.5 4.25 4.25 0 0 0 0-8.5zM10.25 10.25 13.5 13.5',
  chat: 'M2.75 3.25h10.5v7.5H7.5L4.5 13.25v-2.5H2.75z',
  clock: 'M8 2.25a5.75 5.75 0 1 0 0 11.5 5.75 5.75 0 0 0 0-11.5zM8 5v3.25l2.25 1.5',
  doc: 'M4 1.75h5.25L12.5 5v9.25H4zM9 1.75v3.5h3.5M6 8.5h4M6 11h4',
  user: 'M8 2.5a2.75 2.75 0 1 0 0 5.5 2.75 2.75 0 0 0 0-5.5zM2.75 13.75c.6-2.4 2.7-3.75 5.25-3.75s4.65 1.35 5.25 3.75',
} as const;
export type IconName = keyof typeof ICON_PATH;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="18" height="18">
      <path d={ICON_PATH[name]} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * The one row anatomy on the home: leading slot, title, meta, optional chip
 * and arrow. Without a target it renders as static text (.home-pick-static).
 */
export function Row({ lead, label, meta, chip, to, onClick, external, arrow = true, current = false }: {
  lead?: ReactNode;
  label: ReactNode;
  meta?: ReactNode;
  chip?: ReactNode;
  to?: string;
  onClick?: () => void;
  external?: boolean;
  arrow?: boolean;
  /** Marks the row for the page being shown (sidebar). */
  current?: boolean;
}) {
  const body = (
    <>
      {lead !== undefined && <span className="home-row-lead" aria-hidden="true">{lead}</span>}
      <span className="home-row-text">
        <span className="home-row-title">{label}</span>
        {meta && <span className="home-row-meta">{meta}</span>}
      </span>
      {chip}
      {arrow && (
        <svg className="home-row-arrow" aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
          <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </>
  );
  if (to && external) {
    return <li><a className="home-row" href={to} target="_blank" rel="noopener noreferrer">{body}</a></li>;
  }
  if (to) {
    return (
      <li>
        <Link className={`home-row${current ? ' is-current' : ''}`} to={to} onClick={onClick} aria-current={current ? 'page' : undefined}>
          {body}
        </Link>
      </li>
    );
  }
  if (onClick) return <li><button type="button" className="home-row" onClick={onClick}>{body}</button></li>;
  return <li><span className="home-row home-pick-static">{body}</span></li>;
}
