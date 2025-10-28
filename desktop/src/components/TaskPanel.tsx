const SAMPLE_TASKS = [
  {
    id: 'task_001',
    title: 'Approve INV-2043',
    due_at: '2025-05-30',
    status: 'open',
  },
  {
    id: 'task_002',
    title: 'Schedule payment to Bright Supplies',
    due_at: '2025-05-28',
    status: 'open',
  },
];

export function TaskPanel() {
  return (
    <aside className="hidden 2xl:flex 2xl:w-[20rem] p-5 bg-surface-900/80 border-l border-slate-700/40 flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Tasks</h2>
        <button className="text-xs text-accent">View All</button>
      </div>
      <div className="space-y-3">
        {SAMPLE_TASKS.map((task) => (
          <div key={task.id} className="card p-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{task.status === 'open' ? 'Open' : 'Done'}</span>
              <time>{new Date(task.due_at).toLocaleDateString()}</time>
            </div>
            <p className="text-sm text-slate-100">{task.title}</p>
            <button className="text-xs text-accent">Mark done</button>
          </div>
        ))}
      </div>
      <div className="mt-auto">
        <button className="w-full py-2 rounded-lg bg-accent/20 text-accent text-sm">Create Task</button>
      </div>
    </aside>
  );
}
