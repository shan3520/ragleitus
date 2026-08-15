import React, { useState } from 'react';

interface Group {
  id: string;
  name: string;
}

interface SearchBarProps {
  onSearch: (query: string, group_id?: string) => void;
  groups: Group[];
}

export const SearchBar: React.FC<SearchBarProps> = ({ onSearch, groups }) => {
  const [query, setQuery] = useState('');
  const [groupId, setGroupId] = useState<string>('');

  const handleSearch = () => {
    // API invocation logic passes the group_id
    onSearch(query, groupId || undefined);
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
    </div>
  );
};
