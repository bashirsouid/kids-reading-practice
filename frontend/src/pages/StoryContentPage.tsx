/**
 * StoryContentPage - Step 2: Edit the generated title and synopsis.
 *
 * Purpose: Allow users to review and edit the AI-generated story title and synopsis.
 * The user must confirm the synopsis before reference metadata is generated.
 * Panel breakdown is generated later on Step 4.
 *
 * UI Update: Form width increased to max-w-8xl (doubled) and synopsis textarea height
 * increased to 400px (doubled from 200px).
 *
 * Route: /storyContent
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { updateTitle, updateSynopsis, proceedToNextStage, regenerateStoryProfile, getJobStatus } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { Spinner } from '../components/ui/Spinner';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { useWebSocket } from '../hooks/useWebSocket';

interface WebSocketStory {
  title?: string;
  synopsis?: string;
  art_style?: string;
  /** Shared world anchor injected into every panel prompt. */
  story_setting?: string;
  character_bible?: string;
  characters?: Array<{ name: string; description: string }>;
  panels?: Array<{
    index: number;
    caption: string;
    image_prompt: string;
    characters: string[];
    has_image: boolean;
    is_placeholder: boolean;
  }>;
}

export function StoryContentPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [title, setTitle] = useState(state.story?.title || '');
  const [synopsis, setSynopsis] = useState(state.story?.synopsis || '');
  const [error, setError] = useState<string | null>(null);
  const [isWaitingForStory, setIsWaitingForStory] = useState(false);
  const [storyGenerated, setStoryGenerated] = useState(false);
  const [lastSavedSynopsis, setLastSavedSynopsis] = useState(state.story?.synopsis || '');

  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

// Sync with wizard state only once on initial load, NOT on subsequent story updates
   // to avoid overwriting user edits with stale server data.
   const didSyncFromGlobal = React.useRef(false);
   useEffect(() => {
     if (!didSyncFromGlobal.current && state.story) {
       didSyncFromGlobal.current = true;
       if (state.story.title) {
         setTitle(state.story.title);
       }
       if (state.story.synopsis) {
         setSynopsis(state.story.synopsis);
         setLastSavedSynopsis(state.story.synopsis);
       }
       // Character metadata indicates the reference step is ready.
       if (state.story.character_bible) {
         setStoryGenerated(true);
       }
     }
   }, [state.story]);

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'storyContent' });
  }, []);

// Handle story updates from WebSocket - only track generation completion, don't overwrite user edits
   const handleStoryUpdate = useCallback((storyUpdate?: WebSocketStory | null) => {
     if (storyUpdate && storyUpdate.character_bible) {
       setStoryGenerated(true);
     }
   }, []);

  // WebSocket hook to wait for story generation to complete after confirmation
  useWebSocket({
    jobId: state.jobId || '',
    onStoryUpdate: handleStoryUpdate,
    onSlugUpdate: useCallback((slug: string) => dispatch({ type: 'SET_SLUG', payload: slug }), [dispatch]),
    onError: useCallback((msg: string) => {
      setError(msg);
      setIsWaitingForStory(false);
    }, []),
  });

  useEffect(() => {
    if (!state.jobId) return;
    let cancelled = false;

    const refreshStatus = async () => {
      try {
        const status = await getJobStatus(state.jobId!);
        if (cancelled || !status.story) return;

        if (!didSyncFromGlobal.current) {
          didSyncFromGlobal.current = true;
          setTitle(status.story.title || '');
          setSynopsis(status.story.synopsis || '');
          setLastSavedSynopsis(status.story.synopsis || '');
          dispatch({
            type: 'SET_STORY',
            payload: {
              ...(state.story || {}),
              ...status.story,
              master_reference: status.has_reference ? 'ready' : state.story?.master_reference,
            },
          });
        } else if (status.story.character_bible && !storyGenerated) {
          dispatch({
            type: 'SET_STORY',
            payload: {
              ...(state.story || {}),
              art_style: status.story.art_style || state.story?.art_style || '',
              story_setting: status.story.story_setting || '',
              character_bible: status.story.character_bible || '',
              characters: status.story.characters || [],
              panels: state.story?.panels || status.story.panels || [],
              master_reference: status.has_reference ? 'ready' : state.story?.master_reference,
            },
          });
        }

        if (status.story.character_bible) {
          setStoryGenerated(true);
        }
      } catch {
      }
    };

    refreshStatus();
    const interval = window.setInterval(refreshStatus, storyGenerated ? 8000 : 2500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [state.jobId, dispatch, storyGenerated]);

  const handleUpdate = async () => {
    if (!state.jobId) return false;
    setError(null);
    try {
      if (title) await updateTitle(state.jobId, title);
      if (synopsis && synopsis !== lastSavedSynopsis) {
        await updateSynopsis(state.jobId, synopsis);
        setLastSavedSynopsis(synopsis);
      }
      return true;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update story';
      setError(errorMessage);
      return false;
    }
  };

  const handleNext = async () => {
    if (!state.jobId) return;

    const needsProfile = !storyGenerated || synopsis !== lastSavedSynopsis;
    const saved = await handleUpdate();
    if (!saved) return;
    if (!needsProfile) {
      navigate(projectPath('styleReference'));
      return;
    }

    setIsWaitingForStory(true);
    setError(null);

    try {
      const profile = await regenerateStoryProfile(state.jobId);
      dispatch({
        type: 'SET_STORY',
        payload: {
          ...(state.story || {}),
          title,
          synopsis,
          art_style: profile.art_style || state.story?.art_style || '',
          story_setting: profile.story_setting || '',
          character_bible: profile.character_bible || '',
          characters: profile.characters || [],
          panels: state.story?.panels || [],
        },
      });
      setStoryGenerated(true);
      await proceedToNextStage(state.jobId);
      navigate(projectPath('styleReference'));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to proceed';
      setError(errorMessage);
      setIsWaitingForStory(false);
    }
  };

  // Auto-navigate when story is ready and we are waiting
  const handleBack = () => {
    navigate('/');
  };

  // Show loading state while waiting for story generation
  if (isWaitingForStory) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <div className="text-center">
          <Spinner className="mx-auto mb-4" />
          <p className="text-text-dim">Preparing character reference details...</p>
        </div>
      </div>
    );
  }

  // Show loading state while story is being generated
  if (!state.story) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <div className="text-center">
          <Spinner className="mx-auto mb-4" />
          <p className="text-text-dim">Generating your story...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-center">
      <div className="form-section w-full max-w-8xl mt-10">
        <div className="text-xs text-text-dim mb-3">Step 2: Story Content</div>
        <h2 className="text-xl text-gold mb-4">📖 Your Story</h2>

        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        <div className="mb-4">
          <label className="text-xs font-semibold text-text-dim mb-1 block">Title & Synopsis</label>
          <div className="input-area">
            <label>Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={handleUpdate}
            />
          </div>
          <div className="input-area">
            <label>Synopsis</label>
<textarea
               value={synopsis}
               onChange={(e) => {
                 setSynopsis(e.target.value);
                 if (e.target.value !== lastSavedSynopsis) {
                   setStoryGenerated(false);
                 }
               }}
               onBlur={handleUpdate}
               style={{ minHeight: '400px' }}
             />
          </div>
        </div>

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Next: Style & Reference →"
        />
      </div>
    </div>
  );
}
