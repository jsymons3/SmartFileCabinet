import { RecordItem } from '../App';

export type RecordInspectorProps = {
  record: RecordItem | null;
};

export function RecordInspector({ record }: RecordInspectorProps) {
  if (!record) {
    return (
      <aside className="hidden xl:flex xl:w-[28rem] p-6 bg-surface-800/60 border-r border-slate-700/40">
        <div className="m-auto text-center text-slate-500">Select a record to inspect its details.</div>
      </aside>
    );
  }

  return (
    <aside className="hidden xl:flex xl:w-[28rem] p-6 bg-surface-800/60 border-r border-slate-700/40 overflow-y-auto">
      <div className="space-y-6 w-full">
        <section className="card p-5 space-y-3">
          <div className="text-xs uppercase text-slate-400">Summary</div>
          <p className="text-sm text-slate-200">
            {typeof record.fields.summary === 'string'
              ? record.fields.summary
              : 'Add a summary via AI extraction.'}
          </p>
        </section>
        <section className="card p-5 space-y-3">
          <div className="text-xs uppercase text-slate-400">Extracted Fields</div>
          <div className="bg-surface-900/40 rounded-lg p-4 font-mono text-xs text-slate-300 whitespace-pre-wrap">
            {JSON.stringify(record.fields, null, 2)}
          </div>
        </section>
        <section className="card p-5 space-y-3">
          <div className="text-xs uppercase text-slate-400">Actions</div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <button className="rounded-lg bg-accent/20 text-accent py-2">Create Task</button>
            <button className="rounded-lg bg-surface-700/50 text-slate-200 py-2">Export CSV</button>
            <button className="col-span-2 rounded-lg bg-surface-700/50 text-slate-200 py-2">
              Fill PDF from Profile
            </button>
          </div>
        </section>
      </div>
    </aside>
  );
}
