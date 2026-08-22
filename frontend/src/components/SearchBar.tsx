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

  const runSearch = async (q: string, gid?: string): Promise<void> => {
    try {
      const params = new URLSearchParams();
      if (q) {
        params.set('q', q);
      }
      if (gid) {
        params.set('group_id', gid);
      }
      const response = await fetch(`/api/search?${params.toString()}`);
      const data: unknown = await response.json();
      const items = Array.isArray(data)
        ? data
        : data && Array.isArray((data as { items?: unknown }).items)
          ? (data as { items: SearchResult[] }).items
          : [];
      setResults(items as SearchResult[]);
    } catch {
      setResults([]);
    }
  };

  const handleSearch = () => {
    // API invocation logic passes the group_id
    onSearch(query, groupId || undefined);
    void runSearch(query, groupId || undefined);
  };

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
      <button onClick={handleSearch} data-testid="search-button">
        Search
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
