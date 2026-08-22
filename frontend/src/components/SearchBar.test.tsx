import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBar } from './SearchBar';

describe('SearchBar', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders selector and passes correct group_id', () => {
    const handleSearch = jest.fn();
    const groups = [{ id: 'group_1', name: 'Group One' }];
    
    render(<SearchBar onSearch={handleSearch} groups={groups} />);
    
    const selector = screen.getByTestId('group-selector');
    expect(selector).toBeInTheDocument();
    
    fireEvent.change(selector, { target: { value: 'group_1' } });
    const button = screen.getByTestId('search-button');
    fireEvent.click(button);
    
    expect(handleSearch).toHaveBeenCalledWith('', 'group_1');
  });

  it('passes undefined when "Search All" is selected', () => {
    const handleSearch = jest.fn();
    const groups = [{ id: 'group_1', name: 'Group One' }];
    
    render(<SearchBar onSearch={handleSearch} groups={groups} />);
    
    const selector = screen.getByTestId('group-selector');
    fireEvent.change(selector, { target: { value: '' } });
    const button = screen.getByTestId('search-button');
    fireEvent.click(button);
    
    expect(handleSearch).toHaveBeenCalledWith('', undefined);
  });

  it('renders results when the API returns a flat array', async () => {
    const handleSearch = jest.fn();
    const groups = [{ id: 'group_1', name: 'Group One' }];
    jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ id: 'doc_1', name: 'Legacy Flat Result' }]),
    } as unknown as Response);

    render(<SearchBar onSearch={handleSearch} groups={groups} />);

    fireEvent.click(screen.getByTestId('search-button'));

    expect(await screen.findByText('Legacy Flat Result')).toBeInTheDocument();
    expect(screen.getByTestId('search-results').children).toHaveLength(1);
  });

  it('extracts items when the API returns a paginated object', async () => {
    const handleSearch = jest.fn();
    const groups = [{ id: 'group_1', name: 'Group One' }];
    jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          items: [{ id: 'doc_2', name: 'Paginated Result' }],
          total: 1,
        }),
    } as unknown as Response);

    render(<SearchBar onSearch={handleSearch} groups={groups} />);

    fireEvent.click(screen.getByTestId('search-button'));

    expect(await screen.findByText('Paginated Result')).toBeInTheDocument();
    expect(screen.getByTestId('search-results').children).toHaveLength(1);
  });
});
