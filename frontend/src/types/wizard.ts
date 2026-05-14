// Wizard state types

export type StoryMode = 'random' | 'themed' | 'custom' | 'fullstory';

export interface Character {
  name: string;
  description: string;
}

export interface Panel {
  index?: number;
  characters?: string | string[];
  image_prompt?: string;
  caption?: string;
  is_placeholder?: boolean;
  has_image?: boolean;
  image?: string | null;
}

export interface Story {
  title?: string;
  synopsis?: string;
  art_style?: string;
  character_bible?: string;
  master_reference?: string;
  reference_prompt?: string;
  characters?: Character[];
  panels?: Panel[];
}

export interface Progress {
  type?: string;
  percent?: number;
  label?: string;
}

export interface WizardState {
  jobId: string | null;
  slug: string | null;
  mode: StoryMode;
  manualStyle: string;
  story: Story | null;

  page: string;
  modelStatus: 'loading' | 'ready' | 'error';
  progress: Progress;
}

// Actions
export type WizardAction =
  | { type: 'SET_MODE'; payload: StoryMode }
  | { type: 'SET_JOB_ID'; payload: string }
  | { type: 'SET_SLUG'; payload: string }
  | { type: 'SET_STORY'; payload: Story }

  | { type: 'SET_PAGE'; payload: string }
  | { type: 'SET_MODEL_STATUS'; payload: 'loading' | 'ready' | 'error' }
  | { type: 'SET_PROGRESS'; payload: Progress }
  | { type: 'UPDATE_STORY_FIELD'; payload: { field: string; value: unknown } }
  | { type: 'RESET' };
