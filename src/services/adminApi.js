import { reachApi } from './reachApi.js';
// Admin requests. The backend checks the role on every one; nothing here grants access.
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

/** A readable message from a FastAPI error, including which field failed validation. */
export function getErrorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => {
      const field = (item.loc || []).filter((part) => part !== 'body').join('.');
      return field ? `${field}: ${item.msg}` : item.msg;
    }).join('; ');
  }
  return `The request failed (${status}).`;
}

async function request(token, path, method = 'GET', body) {
  const response = await reachApi(`${API_BASE_URL}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(getErrorMessage(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

const RECORDS = '/admin/scholarships';

export const adminApi = {
  summary: (token) => request(token, `${RECORDS}/summary`),
  list: (token, query) => request(token, `${RECORDS}?${query}`),
  detail: (token, id) => request(token, `${RECORDS}/${id}`),
  create: (token, body) => request(token, '/scholarships/', 'POST', body),
  update: (token, id, body) => request(token, `/scholarships/${id}`, 'PUT', body),
  remove: (token, id) => request(token, `/scholarships/${id}`, 'DELETE'),
  verify: (token, id, body) => request(token, `${RECORDS}/${id}/verification`, 'POST', body),
  flag: (token, id, body) => request(token, `${RECORDS}/${id}/flags`, 'POST', body),
  checkSources: (token, id) => request(token, `${RECORDS}/${id}/source-check`, 'POST'),
  archive: (token, id, reason) => request(token, `${RECORDS}/${id}/archive`, 'POST', { reason }),
  restore: (token, id) => request(token, `${RECORDS}/${id}/restore`, 'POST'),
  duplicates: (token) => request(token, `${RECORDS}/duplicates`),
  compare: (token, first, second) => request(token, `${RECORDS}/duplicates/compare?first=${first}&second=${second}`),
  markDuplicate: (token, id, body) => request(token, `${RECORDS}/${id}/duplicate`, 'POST', body),
  saveLink: (token, id, programId, body) => request(token, `/scholarships/${id}/programs/${programId}`, 'PUT', body),
  removeLink: (token, id, programId) => request(token, `/scholarships/${id}/programs/${programId}`, 'DELETE'),
  programs: (token) => request(token, '/programs/?limit=100'),
  universities: (token) => request(token, '/universities/?limit=100'),
};
