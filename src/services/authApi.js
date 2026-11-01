import { reachApi } from './reachApi.js';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

function extractErrorMessage(data, fallback = 'Request failed') {
  if (!data) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    const first = data.detail[0];
    return first?.msg || fallback;
  }
  if (typeof data.message === 'string') return data.message;
  return fallback;
}

export function normalizeUser(rawUser) {
  if (!rawUser) return null;
  const fullName = rawUser.full_name || rawUser.name || '';
  const fallbackName = rawUser.email ? rawUser.email.split('@')[0] : 'Student';
  return {
    ...rawUser,
    id: rawUser.id,
    email: rawUser.email,
    name: fullName.trim() || fallbackName,
    full_name: fullName.trim() || fallbackName,
    role: rawUser.role || 'student',
    created_at: rawUser.created_at || null,
  };
}

export async function loginUser(email, password) {
  const formData = new URLSearchParams();
  formData.append('username', email.trim());
  formData.append('password', password);

  const response = await reachApi(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: formData.toString(),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Incorrect email or password');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return data; // { access_token, token_type }
}

export async function getCurrentUser(token) {
  const response = await reachApi(`${API_BASE_URL}/auth/me`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Session expired or invalid');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return normalizeUser(data);
}

export async function registerUser(fullName, email, password) {
  const response = await reachApi(`${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      full_name: fullName.trim(),
      email: email.trim(),
      password: password,
    }),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMsg = extractErrorMessage(data, 'Failed to create account');
    const error = new Error(errorMsg);
    error.status = response.status;
    throw error;
  }

  return normalizeUser(data);
}


async function postJson(path, body, fallback) {
  const response = await reachApi(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(extractErrorMessage(data, fallback));
    error.status = response.status;
    throw error;
  }
  return data;
}

/** POST /auth/forgot-password -> { message } (same reply whether or not the account exists) */
export function requestPasswordReset(email) {
  return postJson('/auth/forgot-password', { email: email.trim() }, 'Could not send the reset link. Please try again.');
}

/** POST /auth/reset-password -> { message } */
export function resetPassword(token, newPassword) {
  return postJson('/auth/reset-password', { token, new_password: newPassword }, 'Could not reset your password. Please try again.');
}
