// API wrapper functions
import type { Character, Panel } from '../types/wizard';

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
  randomness_level?: number;
}): Promise<{ job_id: string; slug?: string }> {
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

/**
 * Update the shared world/setting anchor for a project. The setting is one
 * sentence (location, time of day, weather, mood, lighting) and is injected
 * into every panel prompt — editing it lets the user steer the visual world
 * without rewriting per-panel scene descriptions.
 */
export async function updateStorySetting(jobId: string, storySetting: string): Promise<void> {
  const response = await fetch(`${API_BASE}/update-story-setting`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, story_setting: storySetting }),
  });
  return handleResponse(response);
}

/**
 * Re-run the LLM character/style/world profile pass. Useful for recovering
 * projects where earlier runs failed to parse characters and left an empty
 * cast (which makes the reference image render blank). Preserves the user's
 * title/synopsis/panels/master reference; only the AI profile fields are
 * replaced.
 */
export async function regenerateStoryProfile(jobId: string): Promise<{
  characters: Character[];
  story_setting?: string;
  art_style?: string;
  character_bible?: string;
}> {
  const response = await fetch(`${API_BASE}/regenerate-story-profile/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function updateCharacters(jobId: string, characters: Character[]): Promise<void> {
  const response = await fetch(`${API_BASE}/update-characters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, characters }),
  });
  return handleResponse(response);
}

export async function generateMasterReference(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/generate-reference/${jobId}`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function generatePanelBreakdown(jobId: string): Promise<{ breakdown?: Panel[]; panels?: number }> {
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

export async function getJobStatus(jobId: string): Promise<{
  job_id: string;
  slug?: string;
  status: string;
  stage: string;
  progress_current: number;
  progress_total: number;
  error?: string | null;
  has_reference?: boolean;
  operations?: Record<string, boolean>;
  story?: {
    title?: string;
    synopsis?: string;
    art_style?: string;
    story_setting?: string;
    character_bible?: string;
    panels?: Panel[];
    characters?: Character[];
  };
}> {
  const response = await fetch(`${API_BASE}/status/${jobId}`);
  return handleResponse(response);
}

export async function updatePanel(jobId: string, panelIndex: number, data: {
    caption?: string;
    image_prompt?: string;
    characters?: string[];
}): Promise<void> {
    const response = await fetch(`${API_BASE}/update-panel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            job_id: jobId,
            panel_index: panelIndex,
            ...data,
        }),
    });
    return handleResponse(response);
}

export async function regeneratePanel(jobId: string, panelIndex: number, modification?: string): Promise<void> {
   const response = await fetch(`${API_BASE}/regenerate-panel`, {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ job_id: jobId, panel_index: panelIndex, modification: modification || '' }),
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

export async function getRecentProjects(): Promise<Array<{ slug: string; title: string; created_at: number; status?: string; stage?: string }>> {
  const response = await fetch(`${API_BASE}/recent`);
  return handleResponse(response);
}

export async function loadProject(slug: string): Promise<{
  job_id: string;
  has_reference: boolean;
  story?: {
    title?: string;
    synopsis?: string;
    art_style?: string;
    story_setting?: string;
    character_bible?: string;
    panels?: Panel[];
    characters?: Character[];
  };
  stage: string;
  status?: string;
  error?: string | null;
}> {
  const response = await fetch(`${API_BASE}/status/slug/${slug}`);
  return handleResponse(response);
}

export async function deleteProject(slug: string): Promise<{ status: string; slug: string }> {
  const response = await fetch(`${API_BASE}/project/${slug}`, {
    method: 'DELETE',
  });
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
