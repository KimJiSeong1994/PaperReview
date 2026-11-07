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
