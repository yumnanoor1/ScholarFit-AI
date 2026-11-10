import { reachApi } from './reachApi.js';
// Admin requests. The backend checks the role on every one; nothing here grants access.
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

/** A readable message from a FastAPI error, including which field failed validation. */
export function getErrorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail.message === 'string') return detail.message;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => {
      const field = (item.loc || []).filter((part) => part !== 'body').join('.');
      return field ? `${field}: ${item.msg}` : item.msg;
    }).join('; ');
  }
  return `The request failed (${status}).`;
}

function createRequestError(data, status) {
  const error = new Error(getErrorMessage(data, status));
  error.status = status;
  if (typeof data?.detail?.code === 'string') error.code = data.detail.code;
  return error;
}

async function request(token, path, method = 'GET', body) {
  const response = await reachApi(`${API_BASE_URL}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw createRequestError(data, response.status);
  }
  return data;
}

async function requestMultipart(token, path, body) {
  const response = await reachApi(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw createRequestError(data, response.status);
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
  discoveryReviews: (token, status, skip = 0, limit = 25, search = '') => {
    const query = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) query.set('status', status);
    if (search.trim()) query.set('q', search.trim());
    return request(token, `${RECORDS}/discovery-reviews?${query.toString()}`);
  },
  reviewDiscovery: (token, id, body) => request(
    token,
    `${RECORDS}/discovery-reviews/${id}/review`,
    'POST',
    body,
  ),
  discoveryPublications: (token, { status, scholarshipId, skip = 0, limit = 25 } = {}) => {
    const query = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) query.set('status', status);
    if (scholarshipId) query.set('scholarship_id', String(scholarshipId));
    return request(token, `${RECORDS}/discovery-publications?${query.toString()}`);
  },
  discoveryPublicationEvents: (token, publicationId, skip = 0, limit = 50) => {
    const query = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    return request(
      token,
      `${RECORDS}/discovery-publications/${encodeURIComponent(publicationId)}/events?${query.toString()}`,
    );
  },
  transitionDiscoveryPublication: (token, publicationId, body) => request(
    token,
    `${RECORDS}/discovery-publications/${encodeURIComponent(publicationId)}/lifecycle`,
    'POST',
    body,
  ),
  discoveryMonitoring: (token) => request(token, `${RECORDS}/discovery-monitoring`),
  startManualDiscovery: (token) => request(token, `${RECORDS}/discovery-runs/manual`, 'POST'),
  discoveryHistory: (token, { status, days = 30, q = '', skip = 0, limit = 10 } = {}) => {
    const query = new URLSearchParams({ days: String(days), skip: String(skip), limit: String(limit) });
    if (status) query.set('status', status);
    if (q.trim()) query.set('q', q.trim());
    return request(token, `${RECORDS}/discovery-history?${query.toString()}`);
  },
  discoverySources: (token) => request(token, `${RECORDS}/discovery-sources`),
  extractScholarshipSource: (token, { sourceType, url, file }) => {
    const body = new FormData();
    body.set('source_type', sourceType);
    if (url) body.set('url', url);
    if (file) body.set('file', file, file.name);
    return requestMultipart(token, `${RECORDS}/import/extract`, body);
  },
};
