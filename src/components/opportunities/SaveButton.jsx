import React from 'react';
import { Bookmark } from 'lucide-react';

export default function SaveButton({ isSaved = false, onToggle, label = null }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (onToggle) onToggle();
      }}
      className="btn"
      style={{
        padding: label ? '6px 12px' : '8px',
        borderRadius: '6px',
        backgroundColor: isSaved ? '#EBF3FA' : 'transparent',
        color: isSaved ? 'var(--color-primary)' : 'var(--color-text-muted)',
        border: `1px solid ${isSaved ? 'var(--color-primary)' : 'var(--color-border)'}`,
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '0.82rem',
        fontWeight: '600',
        transition: 'all 0.2s ease'
      }}
      title={isSaved ? "Remove from saved opportunities" : "Save opportunity"}
    >
      <Bookmark 
        size={16} 
        fill={isSaved ? 'var(--color-primary)' : 'none'} 
        color={isSaved ? 'var(--color-primary)' : 'var(--color-text-muted)'} 
      />
      {label && <span>{isSaved ? 'Saved' : label}</span>}
    </button>
  );
}