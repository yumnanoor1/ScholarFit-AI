import React from 'react';
import SaveButton from './SaveButton';
import { MapPin, Calendar, Building2 } from 'lucide-react';

export default function OpportunityHeader({ title, institution, country, deadline, isSaved, onSaveToggle }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      paddingBottom: '16px',
      borderBottom: '1px solid var(--color-border)',
      marginBottom: '16px'
    }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', color: 'var(--color-dark)', fontWeight: '700', marginBottom: '6px' }}>
          {title}
        </h1>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', fontSize: '0.88rem', color: 'var(--color-text-muted)' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--color-primary)', fontWeight: '600' }}>
            <Building2 size={16} /> {institution}
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <MapPin size={16} /> {country}
          </span>
          {deadline && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <Calendar size={16} /> Deadline: {deadline}
            </span>
          )}
        </div>
      </div>

      <SaveButton isSaved={isSaved} onToggle={onSaveToggle} label="Save Opportunity" />
    </div>
  );
}