import React from 'react';

export default function Select({
  label,
  value,
  onChange,
  options = [],
  error = null,
  required = false,
  name,
  disabled = false
}) {
  return (
    <div className="form-group" style={{ marginBottom: '16px' }}>
      {label && (
        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', marginBottom: '6px', color: 'var(--color-dark)' }}>
          {label} {required && <span style={{ color: 'var(--color-danger)' }}>*</span>}
        </label>
      )}
      <select
        name={name}
        value={value}
        onChange={onChange}
        disabled={disabled}
        style={{
          width: '100%',
          padding: '10px 12px',
          border: error ? '1px solid var(--color-danger)' : '1px solid var(--color-border)',
          borderRadius: '6px',
          fontSize: '0.9rem',
          backgroundColor: disabled ? '#F1F5F9' : '#FFFFFF',
          color: 'var(--color-dark)',
          outline: 'none'
        }}
      >
        {options.map((opt, idx) => (
          <option key={idx} value={typeof opt === 'object' ? opt.value : opt}>
            {typeof opt === 'object' ? opt.label : opt}
          </option>
        ))}
      </select>
      {error && (
        <span style={{ fontSize: '0.78rem', color: 'var(--color-danger)', marginTop: '4px', display: 'block' }}>
          {error}
        </span>
      )}
    </div>
  );
}