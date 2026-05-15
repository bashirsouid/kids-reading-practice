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
import { updateTitle, updateSynopsis, proceedToNextStage } from '../services/api';
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

  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  // Sync with wizard state when story is updated
  useEffect(() => {
    if (state.story?.title) {
      setTitle(state.story.title);
    }
    if (state.story?.synopsis) {
      setSynopsis(state.story.synopsis);
    }
    // Character metadata indicates the reference step is ready.
    if (state.story?.character_bible) {
      setStoryGenerated(true);
    }
  }, [state.story]);

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'storyContent' });
  }, []);

  // Handle story updates from WebSocket
  const handleStoryUpdate = useCallback((storyUpdate?: WebSocketStory | null) => {
    if (storyUpdate && storyUpdate.character_bible) {
      const convertedPanels = (storyUpdate.panels || []).map((p) => ({
        index: p.index,
        caption: p.caption,
        image_prompt: p.image_prompt,
        characters: p.characters,
        image: null,
        is_placeholder: p.is_placeholder,
      }));
      dispatch({
        type: 'SET_STORY',
        payload: {
          title: storyUpdate.title || 'Untitled',
          synopsis: storyUpdate.synopsis || '',
          art_style: storyUpdate.art_style || '',
          story_setting: storyUpdate.story_setting || '',
          character_bible: storyUpdate.character_bible || '',
          characters: storyUpdate.characters || [],
          panels: convertedPanels,
        },
      });
      setStoryGenerated(true);
    }
  }, [dispatch]);

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

  const handleUpdate = async () => {
    if (!state.jobId) return;
    setError(null);
    try {
      if (title) await updateTitle(state.jobId, title);
      if (synopsis) await updateSynopsis(state.jobId, synopsis);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update story';
      setError(errorMessage);
    }
  };

  const handleNext = async () => {
    await handleUpdate();
    if (!state.jobId) return;

    // If reference metadata already exists, just navigate.
    if (storyGenerated) {
      navigate(projectPath('styleReference'));
      return;
    }

    // Otherwise, wait for story generation to complete
    setIsWaitingForStory(true);
    setError(null);

    try {
      await proceedToNextStage(state.jobId);
      // We don't navigate here anymore. 
      // The useEffect below will handle navigation when the WebSocket updates the state.
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to proceed';
      setError(errorMessage);
      setIsWaitingForStory(false);
    }
  };

  // Auto-navigate when story is ready and we are waiting
  useEffect(() => {
    if (isWaitingForStory && storyGenerated) {
      navigate(projectPath('styleReference'));
    }
  }, [isWaitingForStory, storyGenerated, navigate, state.slug]);

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
               onChange={(e) => setSynopsis(e.target.value)}
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
