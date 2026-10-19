/**
 * API client interacting with FastAPI backend endpoints.
 */

const API_BASE = '';

async function handleResponse(response) {
  if (!response.ok) {
    let errorDetail = 'API request failed';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || JSON.stringify(errJson);
    } catch {
      errorDetail = await response.text();
    }
    throw new Error(errorDetail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function createSession(data) {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function startSession(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/start`, {
    method: 'POST',
  });
  return handleResponse(res);
}

export async function getSession(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
  return handleResponse(res);
}

export async function getSessionResults(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/results`);
  return handleResponse(res);
}

export async function getResultDetail(resultId) {
  const res = await fetch(`${API_BASE}/api/results/${resultId}`);
  return handleResponse(res);
}

export async function listBugs(sessionId = null) {
  const url = sessionId
    ? `${API_BASE}/api/bugs?session_id=${encodeURIComponent(sessionId)}`
    : `${API_BASE}/api/bugs`;
  const res = await fetch(url);
  return handleResponse(res);
}

export function getBugReportUrl(bugIdentifier) {
  return `${API_BASE}/api/bugs/${encodeURIComponent(bugIdentifier)}/report`;
}

export async function listRegressionTests() {
  const res = await fetch(`${API_BASE}/api/regression`);
  return handleResponse(res);
}

export async function runRegression() {
  const res = await fetch(`${API_BASE}/api/regression/run`, {
    method: 'POST',
  });
  return handleResponse(res);
}

export async function listRecentSessions() {
  const res = await fetch(`${API_BASE}/api/sessions`);
  return handleResponse(res);
}
