
export default function Button({
  children,
  variant = 'primary', // 'primary', 'secondary', 'outline', 'danger'
  size = 'medium',    // 'small', 'medium', 'large'
  disabled = false,
  onClick,
  type = 'button',
  fullWidth = false,
  icon = null,
  className = '',
}) {
  const buttonSize = size === 'sm' ? 'small' : size;

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`btn btn-${variant}${buttonSize !== 'medium' ? ` btn-${buttonSize}` : ''}${fullWidth ? ' btn-full-width' : ''}${className ? ` ${className}` : ''}`}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </button>
  );
}