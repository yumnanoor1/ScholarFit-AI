import { X } from 'lucide-react';
import { GlowCard } from '../ui/spotlight-card';

export default function Modal({ isOpen, onClose, title, children }) {
  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(28, 31, 38, 0.6)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '16px'
    }}>
      <GlowCard customSize className="card" style={{
        width: '100%',
        maxWidth: '550px',
        backgroundColor: '#FFFFFF',
        borderRadius: '8px',
        boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
        overflow: 'hidden',
        padding: '0'
      }} role="dialog" aria-modal="true" aria-labelledby="modal-title">
        {/* Header de la Modal */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--color-bg)'
        }}>
          <h3 id="modal-title" style={{ fontSize: '1.1rem', color: 'var(--color-dark)' }}>{title}</h3>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px' }}
          >
            <X size={20} color="var(--color-dark)" />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '20px' }}>
          {children}
        </div>
      </GlowCard>
    </div>
  );
}
