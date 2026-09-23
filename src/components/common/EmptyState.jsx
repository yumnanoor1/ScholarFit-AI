import React from 'react';
import { FolderOpen } from 'lucide-react';

export default function EmptyState({
  title = "Aucune donnée trouvée",
  description = "Aucune opportunité ne correspond actuellement aux critères sélectionnés.",
  actionLabel = null,
  onAction = null
}) {
  return (
    <div className="card" style={{
      textAlign: 'center',
      padding: '40px 20px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }}>
      <FolderOpen size={48} color="var(--color-secondary)" style={{ marginBottom: '16px' }} />
      <h3 style={{ fontSize: '1.1rem', color: 'var(--color-dark)', marginBottom: '8px' }}>{title}</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', maxWidth: '400px', marginBottom: '20px' }}>
        {description}
      </p>
      {actionLabel && onAction && (
        <button className="btn btn-primary" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}