// API wrapper functions

const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

async function handleResponse(response: Response) {
  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new ApiError(errorText || `HTTP error ${response.status}`, response.status);
  }
  return response.json();
}

export async function checkHealth(): Promise<{ models_loaded: boolean; models_loading?: boolean }> {
  const response = await fetch(`${API_BASE}/health`);
  return handleResponse(response);
}

export async function generateStory(data: {
  mode: string;
  text?: string;
}): Promise<{ job_id: string }> {
  const response = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse(response);
}

export async function proceedToNextStage(jobId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/proceed/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function updateTitle(jobId: string, title: string): Promise<void> {
  const response = await fetch(`${API_BASE}/update-title`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, title }),
  });
  return handleResponse(response);
}

export async function updateSynopsis(jobId: string, synopsis: string): Promise<void> {
  const response = await fetch(`${API_BASE}/update-synopsis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, synopsis }),
  });
  return handleResponse(response);
}

export async function updateArtStyle(jobId: string, artStyle: string): Promise<void> {
  const response = await fetch(`${API_BASE}/update-art-style`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, art_style: artStyle }),
  });
  return handleResponse(response);
}

export async function generateMasterReference(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/proceed/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function generatePanelBreakdown(jobId: string): Promise<{ breakdown: unknown[] }> {
  const response = await fetch(`${API_BASE}/generate-panel-breakdown/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function generatePanels(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/generate-panels/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function updatePanels(jobId: string, panels: unknown[]): Promise<void> {
  const response = await fetch(`${API_BASE}/update-panels`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, panels }),
  });
  return handleResponse(response);
}

export async function getRecentProjects(): Promise<Array<{ slug: string; title: string; created_at: number }>> {
  const response = await fetch(`${API_BASE}/recent`);
  return handleResponse(response);
}

export async function loadProject(slug: string): Promise<{
  job_id: string;
  has_reference: boolean;
  story: {
    title?: string;
    synopsis?: string;
    art_style?: string;
    panels?: unknown[];
    characters?: unknown[];
  };
  stage: string;
}> {
  const response = await fetch(`${API_BASE}/status/slug/${slug}`);
  return handleResponse(response);
}

export function getPanelImageUrl(jobId: string, index: number): string {
  return `/api/panel-image/${jobId}/${index}`;
}

export function getMasterReferenceUrl(slug: string): string {
  return `/api/master-reference/${slug}`;
}

export function getPreviewUrl(slug: string): string {
  return `/api/preview/${slug}`;
}