import React from 'react';
import { AlertCircle, ArrowRight } from 'lucide-react';

export default function NextActionCard({ actionText, onExecute, category = "Profile Improvement" }) {
  return (
    <div style={{
      backgroundColor: 'var(--color-dark)',
      color: '#FFFFFF',
      padding: '20px',
      borderRadius: '8px',
      marginBottom: '24px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: '16px',
      boxShadow: '0 2px 6px rgba(0,0,0,0.1)'
    }}>
      <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
        <div style={{
          padding: '10px',
          borderRadius: '50%',
          backgroundColor: '#2D333F',
          color: 'var(--color-secondary)',
          flexShrink: 0
        }}>
          <AlertCircle size={24} />
        </div>
        <div>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--color-secondary)', fontWeight: 'bold', letterSpacing: '0.5px' }}>
            Best Next Action ({category})
          </span>
          <p style={{ fontSize: '0.95rem', marginTop: '4px', color: '#F1F5F9', lineHeight: '1.4' }}>
            {actionText || "Complete your English test details to improve university matching accuracy."}
          </p>
        </div>
      </div>

      {onExecute && (
        <button 
          className="btn btn-secondary" 
          onClick={onExecute}
          style={{ flexShrink: 0, padding: '10px 18px', fontSize: '0.88rem', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
        >
          Execute Action <ArrowRight size={16} />
        </button>
      )}
    </div>
  );
}
