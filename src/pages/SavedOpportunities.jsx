import React from 'react';
import { Bookmark, Trash2 } from 'lucide-react';

export default function SavedOpportunities() {
  return (
    <div className="page-container">
      <h1 className="page-title">Saved Opportunities</h1>
      <p className="page-subtitle">Your bookmarked universities, programs, and scholarships.</p>

      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ fontSize: '1rem' }}>M.Sc. Informatics — Technical University of Munich</h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Deadline: May 31, 2025 • Germany</p>
        </div>
        <button className="btn btn-outline" style={{ color: 'var(--color-danger)', borderColor: 'var(--color-danger)' }}>
          <Trash2 size={16} /> Remove
        </button>
      </div>
    </div>
  );
}