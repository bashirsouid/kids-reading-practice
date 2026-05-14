/**
 * StyleReferencePage - Step 3: Select art style and generate master reference image.
 * 
 * Purpose: Allow users to select art style and manage character descriptions.
 * Generates master reference image for character consistency across panels.
 * Proceeding advances job to the panel breakdown step.
 * 
 * Route: /styleReference
 * 
 * Note: Reference generation is explicit; Next is enabled after the reference exists.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import { proceedToNextStage, generateMasterReference, updateArtStyle } from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { ArtStyleSelector } from '../components/style/ArtStyleSelector';
import { CharacterList } from '../components/character/CharacterList';
import { Button } from '../components/ui/Button';
import { useWebSocket } from '../hooks/useWebSocket';

export function StyleReferencePage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [artStyle, setArtStyle] = useState(state.story?.art_style || 'Modern Pixar 3D animation style');
  const [characters, setCharacters] = useState(
    state.story?.characters || []
  );
  const [isGeneratingRef, setIsGeneratingRef] = useState(false);
  // Initialize based on whether the story already has a reference image
  const [hasReference, setHasReference] = useState(
    !!state.story?.master_reference
  );
  const [error, setError] = useState<string | null>(null);
  /** Step-level progress during reference image generation */
  const [refProgress, setRefProgress] = useState<{ step: number; totalSteps: number } | null>(null);

  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'styleReference' });
  }, []);

  // Listen for WebSocket updates for this job
  useWebSocket({
    jobId: state.jobId || '',
    onProgress: (progress, total) => {
      // optional: could update UI progress if desired
    },
    onReferenceReady: () => {
      // Master reference is ready - the WebSocket indicates has_reference is true
      // or the stage has moved to panel_breakdown
      setHasReference(true);
      setIsGeneratingRef(false);
      setRefProgress(null);
    },
    onError: (msg) => {
      setError(msg);
      setIsGeneratingRef(false);
      setRefProgress(null);
    },
    onImageGenerating: (target) => {
      if (target === 'reference') {
        // Blank out the old reference image and show generating state
        setHasReference(false);
        setIsGeneratingRef(true);
        setRefProgress(null);
      }
    },
    onImageProgress: (target, _panelIndex, step, totalSteps) => {
      if (target === 'reference') {
        setRefProgress({ step, totalSteps });
      }
    },
  });

  const handleStyleSelect = async (style: string) => {
    setArtStyle(style);
    if (state.jobId && state.story) {
      dispatch({
        type: 'UPDATE_STORY_FIELD',
        payload: { field: 'art_style', value: style }
      });
      try {
        await updateArtStyle(state.jobId, style);
      } catch (err) {
        console.error('Failed to update art style', err);
      }
    }
  };

  const handleGenerateReference = async () => {
    if (!state.jobId) return;
    setIsGeneratingRef(true);
    setHasReference(false);
    setRefProgress(null);
    setError(null);
    try {
      await updateArtStyle(state.jobId, artStyle);
      await generateMasterReference(state.jobId);
      // WebSocket onReferenceReady will update state
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to generate reference';
      setError(errorMessage);
      setIsGeneratingRef(false);
    }
  };

  const handleNext = async () => {
    if (!state.jobId || !hasReference) return;
    
    try {
      await proceedToNextStage(state.jobId);
      navigate(projectPath('panelBreakdown'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to proceed');
    }
  };

  const handleCharacterUpdate = (idx: number, field: 'name' | 'description', value: string) => {
    const newChars = [...characters];
    newChars[idx] = { ...newChars[idx], [field]: value };
    setCharacters(newChars);
  };

  const handleAddCharacter = () => {
    setCharacters([...characters, { name: `Character ${characters.length + 1}`, description: '' }]);
  };

  const handleRemoveCharacter = (idx: number) => {
    setCharacters(characters.filter((_, i) => i !== idx));
  };

  const handleBack = () => {
    navigate(projectPath('storyContent'));
  };

  // Calculate progress percentage for the ring
  const progressPercent = refProgress
    ? (refProgress.step / refProgress.totalSteps) * 100
    : 0;

  return (
    <div className="main-layout">
      <div className="form-section">
        <div className="text-xs text-text-dim mb-3">Step 3: Style & Reference</div>
        <h2 className="text-xl text-gold mb-4">🎨 Style & Character Reference</h2>

        <div className="mb-4">
          <label className="text-sm font-semibold text-text-dim mb-2 block">Art Style</label>
          <ArtStyleSelector selectedStyle={artStyle} onSelect={handleStyleSelect} />
        </div>

        <div className="mb-4">
          <div className="text-sm font-semibold text-text-dim mb-2">Character Descriptions</div>
          <CharacterList
            characters={characters}
            onUpdate={handleCharacterUpdate}
            onAdd={handleAddCharacter}
            onRemove={handleRemoveCharacter}
          />
        </div>

        <WizardNav
          onBack={handleBack}
          onNext={handleNext}
          nextLabel="Next: Panel Breakdown →"
          nextDisabled={!hasReference || isGeneratingRef}
        />
      </div>

      <div className="form-section">
        <div className="text-sm font-semibold text-text-dim mb-4">Master Reference Image</div>
        <div className="bg-bg p-4 rounded-lg text-center min-h-[300px] flex flex-col justify-center">
          {error && (
            <div className="bg-red-900/50 border border-red-500 text-red-200 p-3 rounded-md mb-3 text-sm">
              <strong>Error:</strong> {error}
              <button 
                onClick={() => setError(null)}
                className="ml-2 text-red-400 hover:text-red-200"
              >
                ×
              </button>
            </div>
          )}
          {hasReference ? (
            <div className="flex flex-col items-center">
              <img
                src={`/api/master-reference/${state.slug}?t=${Date.now()}`}
                alt="Reference"
                className="max-w-full rounded-lg cursor-pointer mx-auto mb-3"
                onError={(e) => {
                  // If image fails to load, indicate that
                  setHasReference(false);
                  setError('Reference image failed to load. Please regenerate.');
                }}
              />
              <Button 
                variant="secondary" 
                size="sm" 
                onClick={handleGenerateReference} 
                disabled={isGeneratingRef}
              >
                {isGeneratingRef ? 'Regenerating...' : '🔄 Regenerate Reference'}
              </Button>
            </div>
          ) : (
            <div>
              {isGeneratingRef ? (
                <div className="flex flex-col items-center py-8">
                  <div className="gen-overlay-inline">
                    <div className="gen-progress-ring-container gen-progress-ring-lg">
                      <svg className="gen-progress-ring" viewBox="0 0 80 80">
                        <circle
                          className="gen-progress-ring-track"
                          cx="40" cy="40" r="34"
                          fill="none"
                          strokeWidth="5"
                        />
                        <circle
                          className="gen-progress-ring-fill"
                          cx="40" cy="40" r="34"
                          fill="none"
                          strokeWidth="5"
                          strokeDasharray={`${2 * Math.PI * 34}`}
                          strokeDashoffset={`${2 * Math.PI * 34 * (1 - progressPercent / 100)}`}
                          strokeLinecap="round"
                        />
                      </svg>
                      <div className="gen-progress-text gen-progress-text-lg">
                        {refProgress
                          ? `${refProgress.step}/${refProgress.totalSteps}`
                          : '...'}
                      </div>
                    </div>
                  </div>
                  <p className="text-text-dim text-sm mt-4">
                    Generating reference image...
                    {refProgress && (
                      <span className="text-accent ml-1">
                        Step {refProgress.step} of {refProgress.totalSteps}
                      </span>
                    )}
                  </p>
                </div>
              ) : (
                <>
                  <div className="py-12 border-2 border-dashed border-white/5 rounded-xl mb-4">
                    <p className="text-text-dim text-sm mb-4">
                      No master reference generated yet.
                    </p>
                    <Button variant="primary" onClick={handleGenerateReference}>🖼️ Generate Reference Image</Button>
                  </div>
                  <p className="text-text-dim text-xs">
                    The reference image ensures character consistency across all panels
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
