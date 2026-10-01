import React, { useState } from 'react';

interface Group {
  id: string;
  name: string;
}

interface SearchResult {
  id?: string;
  name?: string;
  title?: string;
}

interface SearchBarProps {
  onSearch: (query: string, group_id?: string) => void;
  groups: Group[];
}

export const SearchBar: React.FC<SearchBarProps> = ({ onSearch, groups }) => {
  const [query, setQuery] = useState('');
  const [groupId, setGroupId] = useState<string>('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [total, setTotal] = useState(0);

  const runSearch = async (
    q: string,
    gid?: string,
    pageNum: number = page,
    pageSize: number = limit
  ): Promise<void> => {
    try {
      const params = new URLSearchParams();
      if (q) {
        params.set('q', q);
      }
      if (gid) {
        params.set('group_id', gid);
      }
      params.set('skip', String((pageNum - 1) * pageSize));
      params.set('limit', String(pageSize));
      const response = await fetch(`/api/search?${params.toString()}`);
      const data: unknown = await response.json();
      if (Array.isArray(data)) {
        setResults(data as SearchResult[]);
        setTotal(data.length);
      } else if (data && Array.isArray((data as { items?: unknown }).items)) {
        const paginated = data as { items: SearchResult[]; total?: number };
        setResults(paginated.items);
        if (typeof paginated.total === 'number') {
          setTotal(paginated.total);
        }
      } else {
        setResults([]);
        setTotal(0);
      }
    } catch {
      setResults([]);
      setTotal(0);
    }
  };

  const handleSearch = () => {
    setPage(1);
    onSearch(query, groupId || undefined);
    void runSearch(query, groupId || undefined, 1);
  };

  const handlePreviousPage = () => {
    if (page <= 1) {
      return;
    }
    const prevPage = page - 1;
    setPage(prevPage);
    void runSearch(query, groupId || undefined, prevPage);
  };

  const handleNextPage = () => {
    if (page * limit >= total) {
      return;
    }
    const nextPage = page + 1;
    setPage(nextPage);
    void runSearch(query, groupId || undefined, nextPage);
  };

  const handlePageSizeChange = (newLimit: number) => {
    setLimit(newLimit);
    setPage(1);
    void runSearch(query, groupId || undefined, 1, newLimit);
  };

  const start = (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);

  return (
    <div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search..."
        data-testid="search-input"
      />
      <select
        value={groupId}
        onChange={(e) => setGroupId(e.target.value)}
        data-testid="group-selector"
      >
        <option value="">Search All</option>
        {groups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.name}
          </option>
        ))}
      </select>
      <select
        value={limit}
        onChange={(e) => handlePageSizeChange(Number(e.target.value))}
        data-testid="page-size-selector"
      >
        <option value={10}>10</option>
        <option value={20}>20</option>
        <option value={50}>50</option>
      </select>
      <button onClick={handleSearch} data-testid="search-button">
        Search
      </button>
      {total > 0 && (
        <div data-testid="pagination-summary">
          Showing {start}-{end} of {total}
        </div>
      )}
      <button
        onClick={handlePreviousPage}
        disabled={page <= 1}
        data-testid="previous-button"
      >
        Previous
      </button>
      <button
        onClick={handleNextPage}
        disabled={page * limit >= total}
        data-testid="next-button"
      >
        Next
      </button>
      <ul data-testid="search-results">
        {results.map((item, index) => (
          <li
            key={item.id ?? index}
            data-testid={item.id ? `result-${item.id}` : `result-${index}`}
          >
            {item.name || item.title || (item.id != null ? String(item.id) : `Result ${index + 1}`)}
          </li>
        ))}
      </ul>
    </div>
  );
};
