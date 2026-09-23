import React from 'react';
import DocumentCard from './DocumentCard';
import { FileText } from 'lucide-react';

export default function DocumentList({ documents = [], onDelete, onViewDetails }) {
  if (!documents || documents.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
        <FileText size={36} color="var(--color-secondary)" style={{ marginBottom: '10px' }} />
        <h4 style={{ fontSize: '1rem', color: 'var(--color-dark)', marginBottom: '4px' }}>No Documents Uploaded</h4>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
          Upload your academic credentials above to enable automated transcript analysis.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', marginBottom: '14px', color: 'var(--color-dark)' }}>
        Uploaded Academic Records ({documents.length})
      </h3>
      <div>
        {documents.map((doc) => (
          <DocumentCard 
            key={doc.id || doc.name} 
            document={doc} 
            onDelete={onDelete} 
            onViewDetails={onViewDetails} 
          />
        ))}
      </div>
    </div>
  );
}