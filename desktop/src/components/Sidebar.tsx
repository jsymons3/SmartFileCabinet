import { clsx } from 'clsx';

const NAV_ITEMS = [
  'Inbox',
  'All Docs',
  'Invoices',
  'Receipts',
  'Purchase Orders',
  'Tasks',
  'Vendors',
  'Exports',
  'Settings',
];

export function Sidebar() {
  return (
    <nav className="w-64 bg-surface-800/80 backdrop-blur border-r border-slate-700/40 p-4 hidden lg:flex flex-col gap-2">
      <div className="text-xl font-semibold mb-6">Business Hub</div>
      {NAV_ITEMS.map((label) => (
        <button
          key={label}
          className={clsx(
            'text-left px-3 py-2 rounded-lg transition-colors',
            label === 'Inbox'
              ? 'bg-accent/20 text-accent'
              : 'hover:bg-surface-700/60 hover:text-slate-200'
          )}
        >
          {label}
        </button>
      ))}
      <div className="mt-auto p-3 rounded-lg bg-surface-700/40">
        <p className="text-xs text-slate-400 uppercase">Storage</p>
        <p className="text-sm font-medium">Local-Only Vault</p>
      </div>
    </nav>
  );
}
