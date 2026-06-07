import React, { createContext, useContext, useReducer, ReactNode } from 'react';
import { WizardState, WizardAction, StoryMode } from '../types/wizard';

const initialState: WizardState = {
  jobId: null,
  slug: null,
  mode: 'random',
  manualStyle: 'Modern Pixar 3D animation style',
  story: null,

  page: 'home',
  modelStatus: 'loading',
  progress: { type: '', percent: 0, label: '' },
};

function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case 'SET_JOB_ID':
      return { ...state, jobId: action.payload };
    case 'SET_SLUG':
      return { ...state, slug: action.payload };
    case 'SET_MODE':
      return { ...state, mode: action.payload };
    case 'SET_STORY':
      return { ...state, story: action.payload };

    case 'SET_PAGE':
      return { ...state, page: action.payload };
    case 'SET_MODEL_STATUS':
      return { ...state, modelStatus: action.payload };
    case 'SET_PROGRESS':
      return { ...state, progress: action.payload };
    case 'UPDATE_STORY_FIELD':
      if (!state.story) return state;
      return {
        ...state,
        story: {
          ...state.story,
          [action.payload.field]: action.payload.value,
        },
      };
    case 'RESET':
      return { ...initialState, jobId: null, slug: null, story: null, modelStatus: state.modelStatus };
    default:
      return state;
  }
}

interface WizardContextValue {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
}

const WizardContext = createContext<WizardContextValue | undefined>(undefined);

export function WizardProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(wizardReducer, initialState);

  return (
    <WizardContext.Provider value={{ state, dispatch }}>
      {children}
    </WizardContext.Provider>
  );
}

export function useWizard() {
  const context = useContext(WizardContext);
  if (!context) {
    throw new Error('useWizard must be used within a WizardProvider');
  }
  return context;
}
