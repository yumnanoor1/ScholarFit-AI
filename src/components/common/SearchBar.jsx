import React from 'react';
import { Search } from 'lucide-react';

export default function SearchBar({
  value,
  onChange,
  placeholder = "Rechercher une université, un programme ou une bourse..."
}) {
  return (
    <div style={{ position: 'relative', width: '100%', marginBottom: '20px' }}>
      <Search
        size={18}
        color="var(--color-text-muted)"
        style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }}
      />
      <input
        type="text"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        style={{
          width: '100%',
          padding: '10px 12px 10px 40px',
          border: '1px solid var(--color-border)',
          borderRadius: '6px',
          fontSize: '0.9rem',
          backgroundColor: '#FFFFFF',
          outline: 'none',
          color: 'var(--color-dark)'
        }}
      />
    </div>
  );
}