import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { HistoryFilters, EMPTY_HISTORY_FILTERS } from './HistoryFilters';

describe('HistoryFilters', () => {
  it('invokes onChange with the selected action when the action select changes', () => {
    const onChange = jest.fn();
    render(<HistoryFilters filters={EMPTY_HISTORY_FILTERS} onChange={onChange} />);

    fireEvent.change(screen.getByTestId('history-action-filter'), {
      target: { value: 'document_deleted' },
    });

    expect(onChange).toHaveBeenCalledWith({
      action: 'document_deleted',
      entityType: '',
      entityId: '',
    });
  });

  it('invokes onChange with the selected entity type when the entity type select changes', () => {
    const onChange = jest.fn();
    render(<HistoryFilters filters={EMPTY_HISTORY_FILTERS} onChange={onChange} />);

    fireEvent.change(screen.getByTestId('history-entity-type-filter'), {
      target: { value: 'group' },
    });

    expect(onChange).toHaveBeenCalledWith({
      action: '',
      entityType: 'group',
      entityId: '',
    });
  });

  it('invokes onChange with the typed entity ID when the entity ID input changes', () => {
    const onChange = jest.fn();
    render(<HistoryFilters filters={EMPTY_HISTORY_FILTERS} onChange={onChange} />);

    fireEvent.change(screen.getByTestId('history-entity-id-filter'), {
      target: { value: '42' },
    });

    expect(onChange).toHaveBeenCalledWith({
      action: '',
      entityType: '',
      entityId: '42',
    });
  });

  it('preserves the other filter values when a single control changes', () => {
    const onChange = jest.fn();
    render(
      <HistoryFilters
        filters={{ action: 'document_moved', entityType: 'document', entityId: '7' }}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByTestId('history-action-filter'), {
      target: { value: 'document_deleted' },
    });

    expect(onChange).toHaveBeenCalledWith({
      action: 'document_deleted',
      entityType: 'document',
      entityId: '7',
    });
  });

  it('does not make network requests', () => {
    const fetchSpy = jest.spyOn(global, 'fetch');
    const onChange = jest.fn();
    render(<HistoryFilters filters={EMPTY_HISTORY_FILTERS} onChange={onChange} />);

    fireEvent.change(screen.getByTestId('history-action-filter'), {
      target: { value: 'group_created' },
    });

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});