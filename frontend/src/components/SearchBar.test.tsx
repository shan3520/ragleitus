import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SearchBar } from './SearchBar';

const paginatedResponse = (count: number, total: number) => ({
  ok: true,
  json: () =>
    Promise.resolve({
      items: Array.from({ length: count }, (_, i) => ({
        id: `doc_${i + 1}`,
        name: `Doc ${i + 1}`,
      })),
      total,
    }),
});

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

  it('requests the next page from the API when Next is clicked', async () => {
    const fetchMock = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(paginatedResponse(20, 45) as unknown as Response);

    render(<SearchBar onSearch={jest.fn()} groups={[]} />);

    fireEvent.click(screen.getByTestId('search-button'));
    await screen.findByText('Doc 1');
    expect(String(fetchMock.mock.calls[0][0])).toContain('skip=0&limit=20');

    fireEvent.click(screen.getByTestId('next-button'));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));

    expect(String(fetchMock.mock.calls[1][0])).toContain('skip=20&limit=20');
  });

  it('resets the requested page to 1 when the page size changes', async () => {
    const fetchMock = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(paginatedResponse(20, 120) as unknown as Response);

    render(<SearchBar onSearch={jest.fn()} groups={[]} />);

    fireEvent.click(screen.getByTestId('search-button'));
    await screen.findByText('Doc 1');

    fireEvent.click(screen.getByTestId('next-button'));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));
    expect(String(fetchMock.mock.calls[1][0])).toContain('skip=20&limit=20');

    fireEvent.change(screen.getByTestId('page-size-selector'), {
      target: { value: '50' },
    });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(3));

    expect(String(fetchMock.mock.calls[2][0])).toContain('skip=0&limit=50');
    expect(String(fetchMock.mock.calls[2][0])).not.toContain('skip=50');
    expect(String(fetchMock.mock.calls[2][0])).not.toContain('skip=100');
  });

  it('computes the displayed range bounds in the summary', async () => {
    jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(paginatedResponse(20, 45) as unknown as Response);

    render(<SearchBar onSearch={jest.fn()} groups={[]} />);

    fireEvent.click(screen.getByTestId('search-button'));
    expect(await screen.findByText('Showing 1-20 of 45')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('next-button'));
    expect(await screen.findByText('Showing 21-40 of 45')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('next-button'));
    expect(await screen.findByText('Showing 41-45 of 45')).toBeInTheDocument();
  });

  it('resets pagination to page 1 when a new search is submitted', async () => {
    const fetchMock = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(paginatedResponse(20, 45) as unknown as Response);

    render(<SearchBar onSearch={jest.fn()} groups={[]} />);

    fireEvent.change(screen.getByTestId('search-input'), {
      target: { value: 'first' },
    });
    fireEvent.click(screen.getByTestId('search-button'));
    await screen.findByText('Doc 1');

    fireEvent.click(screen.getByTestId('next-button'));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));

    fireEvent.change(screen.getByTestId('search-input'), {
      target: { value: 'second' },
    });
    fireEvent.click(screen.getByTestId('search-button'));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(3));

    expect(String(fetchMock.mock.calls[2][0])).toContain('q=second');
    expect(String(fetchMock.mock.calls[2][0])).toContain('skip=0&limit=20');
    expect(String(fetchMock.mock.calls[2][0])).not.toContain('skip=20&limit=20');
  });
});
