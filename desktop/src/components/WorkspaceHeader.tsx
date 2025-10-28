export function WorkspaceHeader() {
  return (
    <header className="h-16 border-b border-slate-700/40 flex items-center justify-between px-6">
      <div className="flex items-center gap-3">
        <input
          className="bg-surface-800/60 border border-slate-700/60 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/60"
          placeholder="Search documents, vendors, or actions"
        />
        <button className="px-3 py-2 rounded-lg bg-accent/20 text-accent text-sm">+ New</button>
      </div>
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <span className="h-2 w-2 rounded-full bg-green-400"></span>
        Synced • Local Vault
        <div className="w-8 h-8 rounded-full bg-surface-800/60 border border-slate-700/60" />
      </div>
    </header>
  );
}
