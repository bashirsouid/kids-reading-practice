/**
 * PanelImagesPage - Step 5: Generate images for each panel.
 * 
 * Purpose: Generate images for all 6 panels using the art style and descriptions.
 * Displays panel preview grid and progress indicator during generation.
 * Shows per-panel step-level progress via WebSocket.
 * Proceeding advances job to "complete" stage.
 * 
 * Route: /panelImages
 * 
 * Note: This step generates the actual panel images. Next should only proceed after images ready.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { proceedToNextStage, generatePanels, getJobStatus, getPanelImageUrl } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { Button } from '../components/ui/Button';
import { ProgressBar } from '../components/ui/ProgressBar';
import { PanelGrid } from '../components/panel/PanelGrid';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { useWebSocket } from '../hooks/useWebSocket';
import { ImageLightbox } from '../components/ui/ImageLightbox';
import type { PanelGenerationProgress } from '../components/panel/PanelCard';

export function PanelImagesPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 6 });
  const [error, setError] = useState<string | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  /** Per-panel generation state: maps panel index to progress or true (started, no steps yet). */
  const [generatingPanels, setGeneratingPanels] = useState<Record<number, PanelGenerationProgress | true>>({});

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'panelImages' });
  }, []);

  const handleImageGenerating = useCallback((target: 'reference' | 'panel', panelIndex: number | null) => {
    if (target === 'panel' && panelIndex !== null) {
      // Blank out the old panel image and show generating overlay
      setGeneratingPanels(prev => ({ ...prev, [panelIndex]: true }));
      // Mark the panel as not having an image in the story state
      if (state.story?.panels) {
        const updatedPanels = state.story.panels.map((p, i) =>
          i === panelIndex ? { ...p, has_image: false } : p
        );
        dispatch({
          type: 'SET_STORY',
          payload: { ...state.story, panels: updatedPanels },
        });
      }
    }
  }, [state.story, dispatch]);

  const handleImageProgress = useCallback((target: 'reference' | 'panel', panelIndex: number | null, step: number, totalSteps: number) => {
    if (target === 'panel' && panelIndex !== null) {
      setGeneratingPanels(prev => ({
        ...prev,
        [panelIndex]: { step, totalSteps },
      }));
    }
  }, []);

  // Listen for WebSocket updates for panel generation progress
  useWebSocket({
    jobId: state.jobId || '',
    onProgress: (current, total) => {
      setProgress({ current, total });
      if (total > 0 && current < total) {
        setIsGenerating(true);
      }
    },
    onStoryUpdate: (storyUpdate) => {
      if (!storyUpdate) return;
      dispatch({
        type: 'SET_STORY',
        payload: {
          ...(state.story || {}),
          ...storyUpdate,
        },
      });
      // Clear generating state for panels that now have images
      if (storyUpdate.panels) {
        setGeneratingPanels(prev => {
          const next = { ...prev };
          for (const p of storyUpdate.panels!) {
            if (p.has_image && next[p.index] !== undefined) {
              delete next[p.index];
            }
          }
          return next;
        });
      }
    },
    onStageChange: (stage) => {
      if (stage === 'complete') {
        setIsGenerating(false);
        setIsComplete(true);
        setGeneratingPanels({});
      }
    },
    onError: (msg) => {
      setError(msg);
      setIsGenerating(false);
      setGeneratingPanels({});
    },
    onImageGenerating: handleImageGenerating,
    onImageProgress: handleImageProgress,
  });

  useEffect(() => {
    if (!state.jobId) return;

    let cancelled = false;

    const refreshStatus = async () => {
      try {
        const status = await getJobStatus(state.jobId!);
        if (cancelled) return;

        setProgress({
          current: status.progress_current || 0,
          total: status.progress_total || 6,
        });

        if (status.story) {
          dispatch({
            type: 'SET_STORY',
            payload: {
              ...(state.story || {}),
              ...status.story,
            },
          });
        }

        if (status.status === 'generating_panels') {
          setIsGenerating(true);
        }

        if (status.stage === 'complete') {
          setIsGenerating(false);
          setIsComplete(true);
        }

        if (status.error) {
          setError(status.error);
          setIsGenerating(false);
        }
      } catch {
        // WebSocket remains the primary path; keep polling silent unless the explicit generate call fails.
      }
    };

    refreshStatus();
    const interval = window.setInterval(refreshStatus, isGenerating ? 2000 : 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [state.jobId, isGenerating]);

  const handleGenerate = async () => {
    if (!state.jobId) return;
    setIsGenerating(true);
    setProgress({ current: 0, total: panels.filter(p => !p.is_placeholder && !p.has_image).length || 6 });
    setError(null);
    
    // Trigger panel generation using the dedicated endpoint
    try {
      await generatePanels(state.jobId);
      // Panel generation will happen in the background, WebSocket updates progress
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to generate panel images';
      setError(errorMessage);
      setIsGenerating(false);
    }
  };

  const panels = state.story?.panels || [];
  // Check for panels without images (missing = no image generated)
  const panelsWithoutImages = panels.filter(p => !p.is_placeholder && !p.has_image).length;
  const hasPlaceholders = panels.some(p => 
    p.is_placeholder || (p.caption && p.caption.startsWith('[Placeholder'))
  );
  
  // User can proceed to Review only when ALL 6 panels have images generated
  // and there are no placeholders that need editing
  const allPanelsHaveImages = panels.length === 6 && panelsWithoutImages === 0 && !hasPlaceholders;
  const generatingPanelNumber = Math.min(progress.current + 1, progress.total || 1);

  // Find active panel step progress to display in the overall status
  const activeGenEntries = Object.entries(generatingPanels);
  const activeGenPanel = activeGenEntries.find(([_, v]) => v !== true);

  const handleNext = async () => {
    if (state.jobId) {
      await proceedToNextStage(state.jobId);
    }
    navigate(projectPath('review'));
  };

  const handleBack = () => {
    navigate(projectPath('panelBreakdown'));
  };

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 5: Panel Image Generation</div>
        <h2 className="text-xl text-gold mb-4">🎨 Generate Panel Images</h2>

        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        <div className="mb-4">
          <div className="text-sm font-semibold text-text-dim mb-2">Art Style Used</div>
          <div className="bg-surface2 p-3 rounded-lg">
            <span className="text-gold font-semibold">{state.story?.art_style || 'Modern Pixar 3D animation style'}</span>
            <p className="text-text-dim text-xs mt-1">To change art style, you'll need to regenerate the reference in Step 3</p>
          </div>
        </div>

        {hasPlaceholders && (
          <div className="bg-accent/8 border border-accent rounded-lg p-3 mb-3">
            <div className="font-semibold text-accent text-sm mb-1">⚠️ Placeholder Panels Need Text</div>
            <p className="text-text-dim text-xs">The following panels have placeholder text and need to be edited before image generation</p>
          </div>
        )}

        {isGenerating && (
          <div className="mb-4">
            <ProgressBar percent={progress.total ? (progress.current / progress.total) * 100 : 0} />
            <p className="text-text-dim text-sm text-center mt-2">
              {progress.current >= progress.total
                ? 'Finishing panel generation...'
                : `Generating panel ${generatingPanelNumber} of ${progress.total}...`}
            </p>
            {activeGenPanel && (activeGenPanel[1] as { step: number; totalSteps: number }) && (
              <p className="text-accent text-xs text-center mt-1">
                Step {(activeGenPanel[1] as { step: number; totalSteps: number }).step} of {(activeGenPanel[1] as { step: number; totalSteps: number }).totalSteps} inference steps
              </p>
            )}
            {progress.current > 0 && (
              <p className="text-green-300 text-xs text-center mt-1">
                {progress.current} panel{progress.current === 1 ? '' : 's'} ready
              </p>
            )}
          </div>
        )}

        {!isGenerating && isComplete && allPanelsHaveImages && (
          <div className="bg-green-500/10 border border-green-500/40 rounded-lg p-3 mb-3">
            <div className="font-semibold text-green-300 text-sm">All panel images are ready</div>
            <p className="text-text-dim text-xs mt-1">You can continue to the final review.</p>
          </div>
        )}

        {!isGenerating && panelsWithoutImages > 0 && !hasPlaceholders && (
          <div className="bg-accent/8 border-l-4 border-accent rounded-lg p-3 mb-3">
            <div className="font-semibold text-accent text-sm">{panelsWithoutImages} panel{panelsWithoutImages > 1 ? 's' : ''} need generation</div>
            <p className="text-text-dim text-xs mt-1">{panels.map((p, i) => !p.is_placeholder && !p.has_image ? `#${i + 1}` : null).filter(Boolean).join(', ')}</p>
            <Button variant="gold" size="sm" className="mt-2" onClick={handleGenerate}>
              📝 Generate Missing
            </Button>
          </div>
        )}

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Next: Review →"
          nextDisabled={!allPanelsHaveImages || isGenerating}
        />
      </div>

      <div>
        {panels.length > 0 && (
          <PanelGrid
            panels={panels}
            jobId={state.jobId}
            generatingPanels={generatingPanels}
            onPanelClick={(idx) => {
              const panel = panels[idx];
              if (panel?.has_image && state.jobId) {
                setLightboxUrl(getPanelImageUrl(state.jobId, idx));
              }
            }}
          />
        )}
      </div>
      {lightboxUrl && (
        <ImageLightbox src={lightboxUrl} onClose={() => setLightboxUrl(null)} />
      )}
    </div>
  );
}
