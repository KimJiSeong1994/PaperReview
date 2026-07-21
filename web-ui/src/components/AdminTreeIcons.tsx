/* ── Folder icon SVGs (matching MyPage style) ─────────────────────── */

export function FolderIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" className="admin-tree-folder-icon">
      {open ? (
        <>
          <path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1" fill="rgba(99,102,241,0.15)" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5 19h14a2 2 0 0 0 2-2l-3-7H4l-1 7a2 2 0 0 0 2 2z" fill="rgba(99,102,241,0.25)" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : (
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" fill="rgba(156,163,175,0.1)" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

export function ChevronIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" className="admin-tree-chevron">
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

export function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="rgba(156,163,175,0.08)" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="14 2 14 8 20 8" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" fill="rgba(251,191,36,0.1)" stroke="#fbbf24" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CurriculumIcon({ type }: { type: 'fork' | 'custom' }) {
  return type === 'fork' ? (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M7 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm10 0a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm-5 8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" stroke="#818cf8" strokeWidth="1.5" />
      <path d="M7 8v4c0 2 2 4 5 4m5-8v4c0 2-2 4-5 4" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="#a5b4fc" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
