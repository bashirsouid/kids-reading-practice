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
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { flushSync } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { proceedToNextStage, generatePanels, regeneratePanel, getJobStatus, getPanelImageUrl, updatePanel } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { Button } from '../components/ui/Button';
import { ProgressBar } from '../components/ui/ProgressBar';
import { PanelGrid } from '../components/panel/PanelGrid';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { useWebSocket } from '../hooks/useWebSocket';
import { ImageLightbox } from '../components/ui/ImageLightbox';
import { PanelModal } from '../components/panel/PanelModal';
import type { PanelGenerationProgress } from '../components/panel/PanelCard';

export function PanelImagesPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 6 });
  const [error, setError] = useState<string | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [modalPanelIndex, setModalPanelIndex] = useState<number | null>(null);
  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  const [generatingPanels, setGeneratingPanels] = useState<Record<number, PanelGenerationProgress | true>>({});
  const [panelCacheKeys, setPanelCacheKeys] = useState<Record<number, number>>({});

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'panelImages' });
  }, []);

  const handleImageGenerating = useCallback((target: 'reference' | 'panel', panelIndex: number | null) => {
    if (target === 'panel' && panelIndex !== null) {
      setPanelCacheKeys(prev => ({ ...prev, [panelIndex]: Date.now() }));
      setGeneratingPanels(prev => ({ ...prev, [panelIndex]: true }));
      setIsGenerating(true);
      setIsComplete(false);
    }
  }, []);

  const handleImageProgress = useCallback((target: 'reference' | 'panel', panelIndex: number | null, step: number, totalSteps: number) => {
    if (target === 'panel' && panelIndex !== null) {
      setGeneratingPanels(prev => ({
        ...prev,
        [panelIndex]: { step, totalSteps },
      }));
    }
  }, []);

  useWebSocket({
    jobId: state.jobId || '',
    onProgress: (current, total) => {
      setProgress({ current, total });
      if (total > 0 && current < total) {
        setIsGenerating(true);
      }
    },
    onStoryUpdate: (storyUpdate) => {
      if (!storyUpdate?.panels) return;

      const currentPanels = state.story?.panels;
      // Sync panels from server if we don't have them locally yet, or merge updates
      if (storyUpdate.panels.length > 0) {
        const serverPanels = storyUpdate.panels;
        // Merge has_image flags - update local panels with server state
        const updatedPanels = (currentPanels?.length ? currentPanels : [...serverPanels]).map(panel => {
          const serverPanel = serverPanels.find(sp => sp.index === panel.index);
          if (serverPanel?.has_image) {
            return { ...panel, has_image: true };
          }
          return panel;
        });
        dispatch({
          type: 'SET_STORY',
          payload: { ...(state.story || {}), panels: updatedPanels },
        });
        const completedIndices = serverPanels.filter(sp => sp.has_image).map(sp => sp.index);
        setPanelCacheKeys(prev => {
          const next = { ...prev };
          for (const idx of completedIndices) {
            next[idx] = Date.now();
          }
          return next;
        });
        setGeneratingPanels(prev => {
          const next = { ...prev };
          for (const idx of completedIndices) {
            if (next[idx] !== undefined) {
              delete next[idx];
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

        const currentPanels = state.story?.panels;
        // Sync panels from server - update has_image flags and load initial panels if needed
        if (status.story?.panels && status.story.panels.length > 0) {
          const serverPanels = status.story.panels;
          // Use existing panels if available, otherwise initialize from server
          const panelsToUpdate = (currentPanels?.length ? currentPanels : [...serverPanels]).map(panel => {
            const serverPanel = serverPanels.find(sp => sp.index === panel.index);
            if (serverPanel?.has_image) {
              return { ...panel, has_image: true };
            }
            return panel;
          });
          dispatch({
            type: 'SET_STORY',
            payload: {
              ...(state.story || {}),
              ...status.story,
              panels: panelsToUpdate,
            },
          });
          const completedIndices = serverPanels.filter(sp => sp.has_image).map(sp => sp.index);
          setPanelCacheKeys(prev => {
            const next = { ...prev };
            for (const idx of completedIndices) {
              next[idx] = Date.now();
            }
            return next;
          });
          setGeneratingPanels(prev => {
            const next = { ...prev };
            for (const idx of completedIndices) {
              if (next[idx] !== undefined) {
                delete next[idx];
              }
            }
            return next;
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
      }
    };

    refreshStatus();
    const interval = window.setInterval(refreshStatus, isGenerating ? 2000 : 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [state.jobId, isGenerating, dispatch]);

  const handleGenerate = async () => {
    if (!state.jobId) return;
    setIsGenerating(true);
    const panels = state.story?.panels || [];
    setProgress({ current: 0, total: panels.filter(p => !p.is_placeholder && !p.has_image).length || 6 });
    setError(null);

    try {
      await generatePanels(state.jobId);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to generate panel images';
      setError(errorMessage);
      setIsGenerating(false);
    }
  };

  const panels = state.story?.panels || [];

  const handlePanelClick = (idx: number) => {
    const panel = panels[idx];
    if (panel?.has_image && state.jobId) {
      setModalPanelIndex(idx);
    }
  };

  const handleCloseModal = () => {
    setModalPanelIndex(null);
  };

  const handleRegeneratePanel = useCallback(async (panelIndex: number, prompt?: string) => {
    if (!state.jobId) return;
    // Prevent duplicate regeneration calls
    if (generatingPanels[panelIndex] !== undefined) return;
    
    // Immediately mark panel as generating to prevent duplicate clicks
    // Use flushSync to ensure state update happens synchronously for UI feedback
    flushSync(() => {
      setPanelCacheKeys(prev => ({ ...prev, [panelIndex]: Date.now() }));
      setGeneratingPanels(prev => ({ ...prev, [panelIndex]: true }));
    });
    
    try {
      // Use provided prompt or get from current panel state
      const imagePrompt = prompt ?? panels[panelIndex]?.image_prompt;
      await regeneratePanel(state.jobId, panelIndex, imagePrompt);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to regenerate panel';
      setError(errorMessage);
      // Clean up generating state on error
      setGeneratingPanels(prev => {
        const next = { ...prev };
        delete next[panelIndex];
        return next;
      });
    }
  }, [state.jobId, panels, generatingPanels]);

  const handleUpdatePanel = useCallback(async (index: number, field: string, value: string) => {
    if (!state.story?.panels) return;
    const newPanels = [...state.story.panels];
    const newCaption = field === 'caption' ? value : newPanels[index].caption;
    const newImagePrompt = field === 'image_prompt' ? value : newPanels[index].image_prompt;
    // Check if BOTH required fields are filled (not placeholder or empty)
    const hasRealCaption = newCaption && !newCaption.startsWith('[Placeholder');
    const hasRealImagePrompt = newImagePrompt && !newImagePrompt.startsWith('[Placeholder');
    // Panel is no longer a placeholder when both required fields have real content
    const stillPlaceholder = !(hasRealCaption && hasRealImagePrompt);
    newPanels[index] = {
      ...newPanels[index],
      [field]: value,
      is_placeholder: stillPlaceholder,
    };
    dispatch({
      type: 'SET_STORY',
      payload: { ...state.story, panels: newPanels },
    });
    if (state.jobId) {
      try {
        const characters = Array.isArray(newPanels[index].characters)
          ? newPanels[index].characters
          : String(newPanels[index].characters || '').split(',').map((name) => name.trim()).filter(Boolean);
        await updatePanel(state.jobId, index, {
          caption: field === 'caption' ? value : undefined,
          image_prompt: field === 'image_prompt' ? value : undefined,
          characters: field === 'characters' ? characters : undefined,
        });
      } catch (err) {
        console.error('Failed to update panel:', err);
      }
    }
  }, [state.story, state.jobId, dispatch]);

  const panelsWithoutImages = panels.filter(p => !p.is_placeholder && !p.has_image).length;
  const hasPlaceholders = panels.some(p =>
    p.is_placeholder || (p.caption && p.caption.startsWith('[Placeholder'))
  );

  const allPanelsHaveImages = panels.length === 6 && panelsWithoutImages === 0 && !hasPlaceholders;
  const generatingPanelNumber = Math.min(progress.current + 1, progress.total || 1);

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

  const activeModalPanel = modalPanelIndex !== null ? panels[modalPanelIndex] : null;

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 5: {state.story?.title ? `${state.story.title} - ` : ''}Panel Image Generation</div>
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
            columns={2}
            generatingPanels={generatingPanels}
            panelCacheKeys={panelCacheKeys}
            onPanelClick={handlePanelClick}
            onRegenerate={handleRegeneratePanel}
          />
        )}
      </div>

      {lightboxUrl && (
        <ImageLightbox src={lightboxUrl} onClose={() => setLightboxUrl(null)} />
      )}

{activeModalPanel && modalPanelIndex !== null && state.jobId && (
         <PanelModal
           isOpen={true}
           onClose={handleCloseModal}
           panel={activeModalPanel}
           panelIndex={modalPanelIndex}
           jobId={state.jobId}
           onRegenerate={async (prompt: string) => handleRegeneratePanel(modalPanelIndex, prompt)}
           onUpdatePanel={handleUpdatePanel}
           isRegenerating={generatingPanels[modalPanelIndex] !== undefined}
           regenerationProgress={
             generatingPanels[modalPanelIndex] && generatingPanels[modalPanelIndex] !== true
               ? generatingPanels[modalPanelIndex] as { step: number; totalSteps: number }
               : null
           }
           cacheKey={panelCacheKeys[modalPanelIndex]}
         />
       )}
    </div>
  );
}
