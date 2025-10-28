import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { Sidebar } from './components/Sidebar';
import { ThreadList } from './components/ThreadList';
import { RecordInspector } from './components/RecordInspector';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import { TaskPanel } from './components/TaskPanel';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

export type RecordItem = {
  id: string;
  document_id: string;
  type: string;
  created_at: string;
  fields: Record<string, unknown>;
};

export default function App() {
  const [selectedRecord, setSelectedRecord] = useState<RecordItem | null>(null);
  const { data: records } = useQuery({
    queryKey: ['records'],
    queryFn: async () => {
      const response = await axios.get<RecordItem[]>(`${API_BASE}/records`);
      return response.data;
    },
  });

  const sortedRecords = useMemo(() => {
    return (records ?? []).slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [records]);

  return (
    <div className="flex h-screen bg-surface-900 text-slate-100">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <WorkspaceHeader />
        <div className="flex flex-1 overflow-hidden">
          <ThreadList
            records={sortedRecords}
            onSelect={setSelectedRecord}
            selectedRecordId={selectedRecord?.id}
          />
          <RecordInspector record={selectedRecord} />
          <TaskPanel />
        </div>
      </div>
    </div>
  );
}
