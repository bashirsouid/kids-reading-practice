/**
 * StyleReferencePage - Step 3: Select art style and generate master reference image.
 * 
 * Purpose: Allow users to select art style and preview the reference prompt.
 * Generates master reference image for character consistency across panels.
 * The reference is generated from the synopsis + characters + selected style.
 * Proceeding advances job to the panel breakdown step.
 * 
 * Route: /styleReference
 * 
 * Note: Reference generation is explicit; Next is enabled after the reference exists.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWizard } from '../context/WizardContext';
import {
  proceedToNextStage,
  generateMasterReference,
  updateArtStyle,
  updateStorySetting,
  regenerateStoryProfile,
  getJobStatus,
} from '../services/api';
import { WizardNav } from '../components/ui/WizardNav';
import { ArtStyleSelector } from '../components/style/ArtStyleSelector';
import { Button } from '../components/ui/Button';
import { useWebSocket } from '../hooks/useWebSocket';

/** Trim a free-text field for the prompt preview, mirroring backend logic. */
function trimSetting(s: string, max = 200): string {
  const clean = (s || '').replace(/\s+/g, ' ').trim().replace(/\.$/, '');
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const sp = cut.lastIndexOf(' ');
  return (sp > max / 2 ? cut.slice(0, sp) : cut) + '...';
}

function compactCharAnchor(c: { name: string; description: string }, max = 260): string {
  const desc = (c.description || '').replace(/\s+/g, ' ').trim();
  if (!desc) return `${c.name}: a distinct character with a unique visual appearance`;
  if (desc.length <= max) return `${c.name}: ${desc}`;
  const cut = desc.slice(0, max);
  const sp = cut.lastIndexOf(' ');
  return `${c.name}: ${(sp > max / 2 ? cut.slice(0, sp) : cut)}...`;
}

const PRESET_STYLES = [
  'Modern Pixar 3D animation style',
  'Classic hand-drawn style',
  'Watercolor painting style',
  'Japanese anime style',
  'Marvel comic book style',
  'Disney traditional animation style',
  'Studio Ghibli style',
  'Low poly 3D style',
  'Pixel art style',
  'Claymation stop motion style',
  'Ink and brush style',
  'Pop art style',
];

export function StyleReferencePage() {
  const navigate = useNavigate();
  const { state, dispatch } = useWizard();
  const [artStyle, setArtStyle] = useState(state.story?.art_style || 'Modern Pixar 3D animation style');
  const [storySetting, setStorySetting] = useState(state.story?.story_setting || '');
  const [isGeneratingRef, setIsGeneratingRef] = useState(false);
  // Initialize based on whether the story already has a reference image
  const [hasReference, setHasReference] = useState(
    !!state.story?.master_reference
  );
  const [error, setError] = useState<string | null>(null);
  /** Step-level progress during reference image generation */
  const [refProgress, setRefProgress] = useState<{ step: number; totalSteps: number } | null>(null);

  const projectPath = (page: string) => state.slug ? `/${state.slug}/${page}` : `/${page}`;

  // NOTE: we used to sync local form state from `state.story` here. That was
  // an attractive nuisance — any WebSocket broadcast (every panel finish,
  // every stage change) overwrites parts of state.story, and if a field was
  // missing from the broadcast payload it'd wipe what the user just typed.
  // Now the textbox is purely a controlled component: initialized from
  // state.story on mount, owned by local state thereafter. The blur handler
  // writes back to the server.

  // Build a preview that mirrors the backend's _generate_reference_prompt
  // exactly — so what the user sees is what the model is given.
  const generateReferencePromptPreview = (): string => {
    if (!state.story) return '';
    const styleStr = (artStyle || 'modern 3D animation, cinematic lighting, high detail').replace(/\.$/, '');
    const setting = trimSetting(storySetting, 160);
    const chars = state.story.characters || [];

    if (chars.length > 0) {
      const names = chars.map(c => c.name).join(', ');
      const charBlock = chars
        .map(c => '- ' + compactCharAnchor(c, 260))
        .join('\n');
      const parts = [
        'Character reference sheet. Lineup of every named character standing '
          + 'side by side in a neutral T-pose against a plain off-white studio '
          + 'background, full body visible head to toe, even soft lighting, '
          + 'clear faces, no text, no labels, no props, no other characters.',
        `Cast (${names}):\n${charBlock}`,
        `Style: ${styleStr}, consistent character design, clean lines, vibrant colors, distinct silhouettes.`,
      ];
      if (setting) {
        parts.push(
          `Color and mood reference for the book (do NOT depict this scene here, this is a plain studio character sheet): ${setting}.`
        );
      }
      return parts.join('\n\n');
    }

    let bible = (state.story.character_bible || '').trim();
    if (bible.length > 800) {
      const cut = bible.slice(0, 800);
      const sp = cut.lastIndexOf(' ');
      bible = (sp > 400 ? cut.slice(0, sp) : cut) + '...';
    }
    const parts = [
      'Character reference sheet. All main characters standing side by side '
        + 'against a plain off-white background, full body visible, even soft '
        + 'lighting, no text, no labels.',
      `Characters: ${bible}`,
      `Style: ${styleStr}, clean lines, vibrant colors.`,
    ];
    if (setting) {
      parts.push(`Color and mood reference for the book: ${setting}.`);
    }
    return parts.join('\n\n');
  };

  useEffect(() => {
    dispatch({ type: 'SET_PAGE', payload: 'styleReference' });
  }, []);

  // Auto-select first style if none is set, and auto-generate reference on first load
  useEffect(() => {
    const initializeStyleAndGenerate = async () => {
      // Determine the style to use (prefer existing art_style, otherwise use first preset)
      const styleToUse = state.story?.art_style || PRESET_STYLES[0];
      
      // If no art style is set, use the first preset style
      if (!state.story?.art_style && PRESET_STYLES.length > 0) {
        const firstStyle = PRESET_STYLES[0];
        setArtStyle(firstStyle);
        if (state.jobId && state.story) {
          dispatch({
            type: 'UPDATE_STORY_FIELD',
            payload: { field: 'art_style', value: firstStyle }
          });
          try {
            await updateArtStyle(state.jobId, firstStyle);
          } catch (err) {
            console.error('Failed to auto-set art style', err);
          }
        }
      }
      
      // Auto-generate reference if no reference exists and not already generating
      if (!hasReference && !isGeneratingRef && state.jobId) {
        setIsGeneratingRef(true);
        setHasReference(false);
        setRefProgress(null);
        setError(null);
        try {
          await updateArtStyle(state.jobId, styleToUse);
          await updateStorySetting(state.jobId, storySetting);
          await generateMasterReference(state.jobId);
        } catch (err) {
          const errorMessage = err instanceof Error ? err.message : 'Failed to generate reference';
          setError(errorMessage);
          setIsGeneratingRef(false);
        }
      }
    };
    
    initializeStyleAndGenerate();
  }, []); // Run once on mount

  // Listen for WebSocket updates for this job
  useWebSocket({
    jobId: state.jobId || '',
    onProgress: (progress, total) => {
      // optional: could update UI progress if desired
    },
    onReferenceReady: () => {
      // Master reference is ready - the WebSocket indicates has_reference is true
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

  useEffect(() => {
    if (!state.jobId) return;
    let cancelled = false;

    const refreshStatus = async () => {
      try {
        const status = await getJobStatus(state.jobId!);
        if (cancelled) return;

        if (status.story) {
          dispatch({
            type: 'SET_STORY',
            payload: {
              ...(state.story || {}),
              ...status.story,
              master_reference: status.has_reference ? 'ready' : state.story?.master_reference,
            },
          });
        }

        if (status.has_reference) {
          setHasReference(true);
          setIsGeneratingRef(false);
          setRefProgress(null);
        } else if (status.operations?.reference || status.status === 'generating_reference') {
          setIsGeneratingRef(true);
          setHasReference(false);
        } else {
          setHasReference(false);
        }

        if (status.error) {
          setError(status.error);
          setIsGeneratingRef(false);
        }
      } catch {
      }
    };

    refreshStatus();
    const interval = window.setInterval(refreshStatus, isGeneratingRef || !hasReference ? 2500 : 8000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [state.jobId, dispatch, isGeneratingRef, hasReference]);

  const handleStyleSelect = async (style: string) => {
    const changed = style !== artStyle;
    setArtStyle(style);
    if (state.jobId && state.story) {
      dispatch({
        type: 'UPDATE_STORY_FIELD',
        payload: { field: 'art_style', value: style }
      });
      try {
        await updateArtStyle(state.jobId, style);
        if (changed) {
          setHasReference(false);
        }
      } catch (err) {
        console.error('Failed to update art style', err);
      }
    }
  };

  // Persist the world/setting anchor on blur. The local state mirrors what
  // gets sent to the model, so the prompt preview updates as the user types.
  const handleStorySettingBlur = async () => {
    if (!state.jobId || !state.story) return;
    const changed = storySetting !== (state.story.story_setting || '');
    dispatch({
      type: 'UPDATE_STORY_FIELD',
      payload: { field: 'story_setting', value: storySetting },
    });
    try {
      await updateStorySetting(state.jobId, storySetting);
      if (changed) {
        setHasReference(false);
      }
    } catch (err) {
      console.error('Failed to update story setting', err);
      setError(err instanceof Error ? err.message : 'Failed to update world setting');
    }
  };

  const [isRegeneratingProfile, setIsRegeneratingProfile] = useState(false);

  // Recovery path for projects where an earlier run produced an empty/garbage
  // character bible (the old parser was broken on compound words). This
  // re-runs the LLM profile pass without touching title/synopsis/panels.
  const handleRegenerateProfile = async () => {
    if (!state.jobId || !state.story) return;
    setIsRegeneratingProfile(true);
    setError(null);
    try {
      const result = await regenerateStoryProfile(state.jobId);
      // Push the new profile into wizard state so the preview reflects it.
      dispatch({
        type: 'SET_STORY',
        payload: {
          ...state.story,
          art_style: result.art_style || state.story.art_style,
          story_setting: result.story_setting || '',
          character_bible: result.character_bible || '',
          characters: result.characters || [],
        },
      });
      if (result.art_style) setArtStyle(result.art_style);
      if (result.story_setting !== undefined) setStorySetting(result.story_setting || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate story profile');
    } finally {
      setIsRegeneratingProfile(false);
    }
  };

  const handleGenerateReference = async () => {
    if (!state.jobId) return;
    setIsGeneratingRef(true);
    setHasReference(false);
    setRefProgress(null);
    setError(null);
    try {
      // Flush any pending edits before kicking off generation so the
      // reference is built from exactly what the user sees in the preview.
      await updateArtStyle(state.jobId, artStyle);
      await updateStorySetting(state.jobId, storySetting);
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

  const handleCharacterUpdate = async (idx: number, field: 'name' | 'description', value: string) => {
    // Removed: character management is now handled by synopsis + structured characters
  };

  const handleAddCharacter = async () => {
    // Removed: character management is now handled by synopsis + structured characters
  };

  const handleRemoveCharacter = async (idx: number) => {
    // Removed: character management is now handled by synopsis + structured characters
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
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-xs text-text-dim mb-1">Step 3: {state.story?.title ? `${state.story.title} - ` : ''}Style & Reference</div>
            <h2 className="text-xl text-gold">🎨 Style & Reference Image</h2>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRegenerateProfile}
            disabled={isRegeneratingProfile}
            title="Re-run the LLM character/style/world pass. Useful if the reference image came out blank — usually means the character bible parse failed in an earlier run."
          >
            {isRegeneratingProfile ? 'Regenerating…' : '🔄 Regenerate Story Profile'}
          </Button>
        </div>

        {state.story?.characters && state.story.characters.length === 0 && (
          <div className="bg-amber-900/40 border border-amber-500/40 text-amber-200 p-3 rounded-md mb-3 text-xs">
            <strong>No characters detected.</strong> The character bible
            didn't parse — the reference image will be blank. Click{' '}
            <em>Regenerate Story Profile</em> above to retry the LLM pass.
          </div>
        )}

        <div className="mb-4">
          <div className="input-area">
            <label>World / Setting</label>
            <textarea
              value={storySetting}
              onChange={(e) => setStorySetting(e.target.value)}
              onBlur={handleStorySettingBlur}
              placeholder='One sentence — location, time of day, weather, mood, lighting. e.g. "a misty pine forest at twilight, soft moonlight, glowing fireflies"'
              rows={3}
              style={{ minHeight: '70px' }}
            />
          </div>
          <div className="text-xs text-text-dim mt-1">
            Injected into every panel prompt as a shared world anchor. Keep it
            tight (one sentence) — it locks the visual world across all panels.
          </div>
        </div>

        <div className="mb-4">
          <label className="text-sm font-semibold text-text-dim mb-2 block">Art Style</label>
          <ArtStyleSelector selectedStyle={artStyle} onSelect={handleStyleSelect} />
        </div>

        <div className="mb-6 p-4 bg-bg border border-border rounded-lg">
          <div className="text-sm font-semibold text-text-dim mb-3">Reference Prompt Preview</div>
          <div className="text-sm text-text-secondary leading-relaxed bg-bg-darker p-3 rounded border border-border-dim max-h-56 overflow-y-auto font-mono text-xs whitespace-pre-wrap">
            {generateReferencePromptPreview()}
          </div>
          <div className="text-xs text-text-dim mt-2">
            Clean character-sheet prompt. The reference image is a neutral
            lineup — its job is to anchor character look and color palette.
            Composition for each panel comes from the panel's scene description.
          </div>
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
