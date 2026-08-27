import React from 'react';
import { render, screen } from '@testing-library/react';
import { HistoryItem, HistoryItemRecord } from './HistoryItem';

const activeRecord: HistoryItemRecord = {
  id: 1,
  action: 'document_uploaded',
  document_id: 10,
  timestamp: '2026-08-01T10:00:00Z',
};

const deletedRecord: HistoryItemRecord = {
  id: 2,
  action: 'document_deleted',
  document_id: 11,
  timestamp: '2026-08-02T10:00:00Z',
};

describe('HistoryItem', () => {
  it('renders the timestamp, action, and entity name for an active entity', () => {
    render(<HistoryItem record={activeRecord} />);

    expect(screen.getByText('2026-08-01T10:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('document_uploaded')).toBeInTheDocument();
    expect(screen.getByText('Item 10')).toBeInTheDocument();
  });

  it('renders the snapshotted entity name when provided', () => {
    const record: HistoryItemRecord = {
      ...activeRecord,
      entityName: 'Quarterly Report',
    };
    render(<HistoryItem record={record} />);

    expect(screen.getByText('Quarterly Report')).toBeInTheDocument();
  });

  it('renders a Deleted badge and grayed styling when the action is a deletion', () => {
    render(<HistoryItem record={deletedRecord} />);

    expect(screen.getByTestId('deleted-badge')).toHaveTextContent('Deleted');
    expect(screen.getByTestId('history-item-2').className).toContain(
      'history-item--deleted'
    );
  });

  it('does not render deletion cues for an active entity', () => {
    render(<HistoryItem record={activeRecord} />);

    expect(screen.queryByTestId('deleted-badge')).not.toBeInTheDocument();
    expect(screen.getByTestId('history-item-1').className).not.toContain(
      'history-item--deleted'
    );
  });

  it('respects an explicit is_deleted flag over the action type', () => {
    const flaggedActive: HistoryItemRecord = {
      id: 3,
      action: 'document_deleted',
      document_id: 12,
      timestamp: '2026-08-03T10:00:00Z',
      is_deleted: false,
    };
    render(<HistoryItem record={flaggedActive} />);

    expect(screen.queryByTestId('deleted-badge')).not.toBeInTheDocument();
  });
});
