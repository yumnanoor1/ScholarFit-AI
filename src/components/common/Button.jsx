import React from 'react';

export default function Button({
  children,
  variant = 'primary', // 'primary', 'secondary', 'outline', 'danger'
  size = 'medium',    // 'small', 'medium', 'large'
  disabled = false,
  onClick,
  type = 'button',
  fullWidth = false,
  icon = null
}) {
  let backgroundColor = 'var(--color-primary)';
  let color = '#FFFFFF';
  let border = 'none';

  if (variant === 'secondary') {
    backgroundColor = 'var(--color-secondary)';
  } else if (variant === 'outline') {
    backgroundColor = 'transparent';
    color = 'var(--color-primary)';
    border = '1px solid var(--color-primary)';
  } else if (variant === 'danger') {
    backgroundColor = 'var(--color-danger)';
  }

  let padding = '10px 18px';
  let fontSize = '0.9rem';

  if (size === 'small') {
    padding = '6px 12px';
    fontSize = '0.8rem';
  } else if (size === 'large') {
    padding = '14px 24px';
    fontSize = '1rem';
  }

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      style={{
        backgroundColor: disabled ? '#CBD5E1' : backgroundColor,
        color: disabled ? '#64748B' : color,
        border: border,
        padding: padding,
        fontSize: fontSize,
        borderRadius: '6px',
        fontWeight: '600',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        width: fullWidth ? '100%' : 'auto',
        transition: 'opacity 0.2s ease',
        opacity: disabled ? 0.7 : 1
      }}
    >
      {icon && <span>{icon}</span>}
      {children}
    </button>
  );
}