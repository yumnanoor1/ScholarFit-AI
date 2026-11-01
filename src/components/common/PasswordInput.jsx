import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';

/**
 * Password field with a show/hide toggle.
 * Accepts the same props as <input>; `style` is applied to the input itself.
 */
export default function PasswordInput({ className = 'auth-form-input', style, ...inputProps }) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-field">
      <input
        {...inputProps}
        className={className}
        type={visible ? 'text' : 'password'}
        style={{ ...style, paddingRight: '44px' }}
      />
      <button
        type="button"
        className="password-toggle"
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        title={visible ? 'Hide password' : 'Show password'}
        onClick={() => setVisible((current) => !current)}
      >
        {visible ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
      </button>
    </div>
  );
}
