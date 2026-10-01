import React from 'react';

export type HistoryEntityType = 'document' | 'group';

export interface HistoryFiltersState {
  action: string;
  entityType: '' | HistoryEntityType;
  entityId: string;
}

export const EMPTY_HISTORY_FILTERS: HistoryFiltersState = {
  action: '',
  entityType: '',
  entityId: '',
};

export const HISTORY_ACTIONS = [
  'document_uploaded',
  'document_moved',
  'document_deleted',
  'group_created',
  'group_updated',
  'group_deleted',
];

interface HistoryFiltersProps {
  filters: HistoryFiltersState;
  onChange: (filters: HistoryFiltersState) => void;
}

export const HistoryFilters: React.FC<HistoryFiltersProps> = ({ filters, onChange }) => {
  const update = (patch: Partial<HistoryFiltersState>) => {
    onChange({ ...filters, ...patch });
  };

  return (
    <div data-testid="history-filters">
      <label htmlFor="history-action-filter">
        Action
        <select
          id="history-action-filter"
          data-testid="history-action-filter"
          value={filters.action}
          onChange={(e) => update({ action: e.target.value })}
        >
          <option value="">All actions</option>
          {HISTORY_ACTIONS.map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor="history-entity-type-filter">
        Entity type
        <select
          id="history-entity-type-filter"
          data-testid="history-entity-type-filter"
          value={filters.entityType}
          onChange={(e) =>
            update({ entityType: e.target.value as '' | HistoryEntityType })
          }
        >
          <option value="">Any entity</option>
          <option value="document">Document</option>
          <option value="group">Group</option>
        </select>
      </label>
      <label htmlFor="history-entity-id-filter">
        Entity ID
        <input
          id="history-entity-id-filter"
          type="text"
          data-testid="history-entity-id-filter"
          value={filters.entityId}
          onChange={(e) => update({ entityId: e.target.value })}
          placeholder="Entity ID"
        />
      </label>
    </div>
  );
};