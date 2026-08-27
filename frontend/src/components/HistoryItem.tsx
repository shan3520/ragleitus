import React from 'react';

export interface HistoryItemRecord {
  id: number;
  action: string;
  document_id: number | null;
  timestamp: string;
  entityName?: string;
  is_deleted?: boolean;
}

export const HistoryItem: React.FC<{ record: HistoryItemRecord }> = ({ record }) => {
  const isDeleted =
    record.is_deleted !== undefined ? record.is_deleted : /_deleted$/.test(record.action);

  const displayName = record.entityName
    ? record.entityName
    : record.document_id != null
    ? `Item ${record.document_id}`
    : record.action;

  return (
    <div
      className={`history-item${isDeleted ? ' history-item--deleted' : ''}`}
      data-testid={`history-item-${record.id}`}
    >
      {isDeleted && (
        <span className="history-badge" data-testid="deleted-badge">
          Deleted
        </span>
      )}
      <span className="history-timestamp">{record.timestamp}</span>
      <span className="history-action">{record.action}</span>
      <span className="history-entity">{displayName}</span>
    </div>
  );
};
