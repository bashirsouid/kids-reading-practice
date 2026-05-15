/**
 * PanelBreakdownPage - Step 4: Generate and edit the 6 panel descriptions.
 * 
 * Purpose: Generate 6 panel descriptions with image_prompt and caption fields.
 * Users can edit character names, scene descriptions, and captions for each panel.
 * Proceeding advances job to "panels" stage.
 * 
 * Note: Panels are generated on this step, then edited/confirmed before image generation.
 * 
 * Route: /panelBreakdown
 */
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { generatePanelBreakdown, proceedToNextStage, updatePanels } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';

export function PanelBreakdownPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [panels, setPanels] = useState(state.story?.panels || []);
  const [isGeneratingBreakdown, setIsGeneratingBreakdown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const didRequestBreakdown = useRef(false);
  // Track whether the user has made edits to avoid overwriting them
  const didSyncPanelsFromGlobal = useRef(false);
  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  // Sync panels from wizard state only once on initial load, NOT on subsequent story updates
  // to avoid overwriting user edits with stale server data.
  useEffect(() => {
    if (!didSyncPanelsFromGlobal.current && state.story?.panels && state.story.panels.length > 0) {
      didSyncPanelsFromGlobal.current = true;
      setPanels(state.story.panels);
    }
  }, [state.story]);

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'panelBreakdown' });
  }, []);

  useEffect(() => {
    if (!state.jobId || panels.length > 0 || didRequestBreakdown.current) return;
    didRequestBreakdown.current = true;
    handleRegenerate();
  }, [state.jobId, panels.length]);

  const handleRegenerate = async () => {
    if (!state.jobId) return;
    setError(null);
    setIsGeneratingBreakdown(true);
    try {
      const result = await generatePanelBreakdown(state.jobId);
      const breakdown = result.breakdown || [];
      setPanels(breakdown);
      if (state.story) {
        dispatch({
          type: 'SET_STORY',
          payload: {
            ...state.story,
            panels: breakdown,
          },
        });
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to regenerate panel breakdown';
      setError(errorMessage);
    } finally {
      setIsGeneratingBreakdown(false);
    }
  };

  const handlePanelUpdate = (idx: number, field: string, value: string) => {
    const newPanels = [...panels];
    newPanels[idx] = { ...newPanels[idx], [field]: value };
    setPanels(newPanels);
  };

const handleNext = async () => {
    if (!state.jobId) return;

    // Save panel edits to the backend before proceeding
    try {
      const panelsToUpdate = panels.map((p, idx) => ({
        index: idx,
        caption: p.caption,
        image_prompt: p.image_prompt,
        characters: Array.isArray(p.characters)
          ? p.characters
          : String(p.characters || '').split(',').map((name) => name.trim()).filter(Boolean),
        is_placeholder: p.is_placeholder,
      }));
      await updatePanels(state.jobId, panelsToUpdate);

      // Update global state so edits persist across navigation
      if (state.story) {
        dispatch({
          type: 'SET_STORY',
          payload: {
            ...state.story,
            panels: panelsToUpdate,
          },
        });
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save panel edits';
      setError(errorMessage);
      return;
    }

    // Proceed to panel image generation
    await proceedToNextStage(state.jobId);
    navigate(projectPath('panelImages'));
  };

  const handleBack = () => {
    navigate(projectPath('styleReference'));
  };

  return (
    <div className="flex justify-center">
      <div className="form-section w-full max-w-8xl mt-10">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-xs text-text-dim mb-1">Step 4: Panel Breakdown</div>
            <h2 className="text-xl text-gold">📋 Panel Breakdown</h2>
          </div>
          {panels.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRegenerate}
              disabled={isGeneratingBreakdown}
              title="Re-run the LLM to produce a fresh set of 6 panels. Your character bible, art style, and reference image are preserved."
            >
              {isGeneratingBreakdown ? 'Regenerating…' : '🔄 Regenerate Panels'}
            </Button>
          )}
        </div>

        {error && (
          <ErrorMessage message={error} onDismiss={() => setError(null)} />
        )}

        {panels.length === 0 && (
          <div className="mb-4">
            <p className="text-text-dim text-sm mb-3">
              {isGeneratingBreakdown
                ? 'Generating panel breakdown for review...'
                : 'No panels found. Click below to generate panel breakdown.'}
            </p>
            {!isGeneratingBreakdown && (
              <Button
                variant="primary"
                className="w-full mb-3"
                onClick={handleRegenerate}
              >
                📋 Generate Panel Breakdown
              </Button>
            )}
          </div>
        )}

        <div className="space-y-3">
          {panels.map((panel, idx) => {
            const isPlaceholder = panel.is_placeholder || 
              (panel.caption && panel.caption.startsWith('[Placeholder'));
            return (
              <div key={idx} className={`card mb-3 ${isPlaceholder ? 'border-dashed border-accent' : ''}`}>
                <div className="font-semibold text-gold mb-2">
                  # {idx + 1} Panel {isPlaceholder && <span className="text-accent text-xs">(PLACEHOLDER - Needs Text)</span>}
</div>
                 <div className="input-area mb-2">
                   <label className="text-xs">Characters</label>
                   <input
                     type="text"
                     value={Array.isArray(panel.characters) ? panel.characters.join(', ') : panel.characters || ''}
                     onChange={(e) => handlePanelUpdate(idx, 'characters', e.target.value)}
                     placeholder="Character names..."
                     className="text-sm"
                   />
                 </div>
                 <div className="input-area mb-2">
                  <label className="text-xs">Scene Description</label>
                  <textarea
                    rows={2}
                    value={panel.image_prompt || ''}
                    onChange={(e) => handlePanelUpdate(idx, 'image_prompt', e.target.value)}
                    placeholder="Describe the scene..."
                    className="text-sm"
                  />
                </div>
                <div className="input-area">
                  <label className="text-xs">Caption</label>
                  <textarea
                    rows={1}
                    value={panel.caption || ''}
                    onChange={(e) => handlePanelUpdate(idx, 'caption', e.target.value)}
                    placeholder="Panel caption..."
                    className="text-sm"
                  />
                </div>
              </div>
            );
          })}
        </div>

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Confirm Breakdown & Generate Images →"
          nextDisabled={panels.length === 0 || isGeneratingBreakdown}
        />
      </div>
    </div>
  );
}
