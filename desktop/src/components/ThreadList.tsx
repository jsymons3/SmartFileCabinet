import { RecordItem } from '../App';

export type ThreadListProps = {
  records: RecordItem[];
  selectedRecordId?: string;
  onSelect: (record: RecordItem) => void;
};

export function ThreadList({ records, selectedRecordId, onSelect }: ThreadListProps) {
  return (
    <section className="w-full lg:w-[36rem] border-r border-slate-700/40 overflow-y-auto p-4 flex flex-col gap-3">
      {records.length === 0 && (
        <div className="card p-6 text-center text-slate-400">
          Drag & drop a document or ingest via the API to get started.
        </div>
      )}
      {records.map((record) => {
        const createdAt = new Date(record.created_at).toLocaleString();
        return (
          <article
            key={record.id}
            className={`card p-5 cursor-pointer transition-transform ${
              selectedRecordId === record.id ? 'ring-2 ring-accent' : 'hover:translate-y-[-2px]'
            }`}
            onClick={() => onSelect(record)}
          >
            <header className="flex items-center justify-between mb-3">
              <span className="uppercase text-xs tracking-wide text-slate-400">{record.type}</span>
              <time className="text-xs text-slate-500">{createdAt}</time>
            </header>
            <div className="space-y-2 text-sm text-slate-200">
              <p className="font-semibold text-slate-100">
                {typeof record.fields.vendor === 'string'
                  ? record.fields.vendor
                  : record.fields.merchant || 'Untitled Record'}
              </p>
              {typeof record.fields.summary === 'string' && (
                <p className="text-slate-400 line-clamp-3">{record.fields.summary}</p>
              )}
              {typeof record.fields.total === 'number' && (
                <p className="text-slate-300">Total: ${record.fields.total.toFixed(2)}</p>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
