import React from 'react';
import OpportunityCard from './OpportunityCard';
import EmptyState from '../common/EmptyState';

export default function OpportunityList({ opportunities = [], onSaveToggle, emptyTitle, emptyDescription }) {
  if (!opportunities || opportunities.length === 0) {
    return (
      <EmptyState
        title={emptyTitle || "No Matched Opportunities Found"}
        description={emptyDescription || "Try adjusting your profile specifications or search filters."}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {opportunities.map((item) => (
        <OpportunityCard 
          key={item.id} 
          data={item} 
          onSaveToggle={onSaveToggle} 
        />
      ))}
    </div>
  );
}