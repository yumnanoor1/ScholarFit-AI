import React from 'react';
import { FileText, Trash2, AlertTriangle, CheckCircle2, Clock } from 'lucide-react';

export default function DocumentCard({ document, onDelete, onViewDetails }) {
  if (!document) return null;

  const { id, name, type, uploadDate, status, extractedInfo, missingInfo } = document;

  return (
    <div className="card" style={{ borderLeft: '4px solid var(--color-primary)', marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{
            padding: '10px',
            borderRadius: '6px',
            backgroundColor: '#EBF3FA',
            color: 'var(--color-primary)'
          }}>
            <FileText size={22} />
          </div>
          <div>
            <h4 style={{ fontSize: '1rem', color: 'var(--color-dark)' }}>{name}</h4>
            <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              <Clock size={12} /> Uploaded on {uploadDate} • {type}
            </span>
          </div>
        </div>

        <button 
          onClick={() => onDelete && onDelete(id)} 
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '6px', color: 'var(--color-text-muted)' }}
          title="Remove document"
        >
          <Trash2 size={18} />
        </button>
      </div>

      {extractedInfo && (
        <div style={{ backgroundColor: '#F8FAFC', padding: '12px', borderRadius: '6px', fontSize: '0.85rem', marginBottom: '10px' }}>
          <strong style={{ color: 'var(--color-dark)', display: 'block', marginBottom: '4px' }}>Extracted Parameters:</strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }}>
            {extractedInfo.degree && <div>• Degree: {extractedInfo.degree}</div>}
            {extractedInfo.cgpa && <div>• CGPA: {extractedInfo.cgpa}</div>}
            {extractedInfo.institution && <div>• Institution: {extractedInfo.institution}</div>}
          </div>
        </div>
      )}

      {missingInfo && missingInfo.length > 0 && (
        <div style={{ backgroundColor: '#FEF3C7', padding: '10px 12px', borderRadius: '6px', fontSize: '0.82rem', color: '#92400E' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold', marginBottom: '4px' }}>
            <AlertTriangle size={15} color="var(--color-warning)" /> Unverified / Missing Fields:
          </div>
          <ul style={{ paddingLeft: '20px', margin: 0 }}>
            {missingInfo.map((info, idx) => (
              <li key={idx}>{info}</li>
            ))}
          </ul>
        </div>
      )}

      {onViewDetails && (
        <div style={{ marginTop: '12px', textAlign: 'right' }}>
          <button 
            className="btn btn-outline" 
            onClick={() => onViewDetails(document)}
            style={{ padding: '4px 12px', fontSize: '0.8rem' }}
          >
            View Extraction Summary
          </button>
        </div>
      )}
    </div>
  );
}