import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBar } from './SearchBar';

describe('SearchBar', () => {
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
});
