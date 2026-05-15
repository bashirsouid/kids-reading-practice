/**
 * PanelModal - Modal for viewing and regenerating a single panel image.
 *
 * Purpose: When clicking a panel image in step 5, opens a modal showing
 * the full image on the right, editable text fields on the left,
 * and a regenerate button with loading spinner.
 *
 * Used by: PanelImagesPage
 */
import React, { useState } from 'react';
import { Dialog, Transition } from '@headlessui/react';
import { Panel } from '../../types/wizard';
import { Button } from '../ui/Button';
import { Spinner } from '../ui/Spinner';
import { regeneratePanel } from '../../services/api';

interface PanelModalProps {
  isOpen: boolean;
  onClose: () => void;
  panel: Panel;
  panelIndex: number;
  jobId: string;
  onRegenerate: () => void;
  onUpdatePanel: (index: number, field: string, value: string) => void;
}

export function PanelModal({
  isOpen,
  onClose,
  panel,
  panelIndex,
  jobId,
  onRegenerate,
  onUpdatePanel,
}: PanelModalProps) {
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imageUrl = `/api/panel-image/${jobId}/${panelIndex}`;

  const handleRegenerate = async () => {
    setIsRegenerating(true);
    setError(null);
    try {
      await regeneratePanel(jobId, panelIndex, panel.image_prompt || '');
      onRegenerate();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate panel');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handlePanelUpdate = (field: string, value: string) => {
    onUpdatePanel(panelIndex, field, value);
  };

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-[1000]" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black/90" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-stretch justify-center p-4 text-center">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-150"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel className="w-full max-w-5xl transform overflow-hidden rounded-xl bg-surface border border-glass shadow-xl transition-all">
                <div className="flex flex-col lg:flex-row">
                  {/* Left side: editable text fields */}
                  <div className="w-full lg:w-1/2 p-6 border-b lg:border-b-0 lg:border-r border-white/10 overflow-y-auto">
                    <div className="text-xs text-text-dim mb-1">Panel #{panelIndex + 1}</div>
                    <h3 className="text-lg font-semibold text-gold mb-4">Edit Panel</h3>

                    {error && (
                      <div className="bg-red-900/20 border border-red-500 text-red-200 px-3 py-2 rounded-md text-sm mb-3">
                        {error}
                        <button
                          onClick={() => setError(null)}
                          className="ml-2 text-red-400 hover:text-red-200 float-right"
                        >
                          ×
                        </button>
                      </div>
                    )}

                    <div className="space-y-3">
                      <div className="input-area">
                        <label className="text-xs">Characters</label>
                        <input
                          type="text"
                          value={Array.isArray(panel.characters) ? panel.characters.join(', ') : panel.characters || ''}
                          onChange={(e) => handlePanelUpdate('characters', e.target.value)}
                          placeholder="Character names..."
                          className="w-full px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm text-text focus:border-accent focus:outline-none"
                        />
                      </div>

                      <div className="input-area">
                        <label className="text-xs">Image Prompt</label>
                        <textarea
                          rows={3}
                          value={panel.image_prompt || ''}
                          onChange={(e) => handlePanelUpdate('image_prompt', e.target.value)}
                          placeholder="Describe the scene..."
                          className="w-full px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm text-text focus:border-accent focus:outline-none resize-vertical"
                        />
                      </div>

                      <div className="input-area">
                        <label className="text-xs">Caption</label>
                        <textarea
                          rows={2}
                          value={panel.caption || ''}
                          onChange={(e) => handlePanelUpdate('caption', e.target.value)}
                          placeholder="Panel caption..."
                          className="w-full px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm text-text focus:border-accent focus:outline-none resize-vertical"
                        />
                      </div>
                    </div>

                    <div className="mt-4 flex gap-2">
                      <Button
                        variant="primary"
                        onClick={handleRegenerate}
                        disabled={isRegenerating}
                        className="flex-1"
                      >
                        {isRegenerating ? (
                          <span className="flex items-center justify-center gap-2">
                            <Spinner size="sm" />
                            Regenerating...
                          </span>
                        ) : (
                          '🔄 Regenerate Image'
                        )}
                      </Button>
                      <Button variant="secondary" onClick={onClose} className="flex-1">
                        Close
                      </Button>
                    </div>
                  </div>

                  {/* Right side: image display */}
                  <div className="w-full lg:w-1/2 p-6 flex flex-col items-center justify-center bg-bg">
                    {isRegenerating ? (
                      <div className="flex flex-col items-center justify-center py-12">
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
                                strokeDashoffset={0}
                                strokeLinecap="round"
                              />
                            </svg>
                            <div className="gen-progress-text gen-progress-text-lg">
                              <Spinner size="sm" />
                            </div>
                          </div>
                        </div>
                        <p className="text-text-dim text-sm mt-4">Regenerating panel image...</p>
                      </div>
                    ) : panel.has_image ? (
                      <>
                        <img
                          src={`${imageUrl}?t=${Date.now()}`}
                          alt={`Panel ${panelIndex + 1}`}
                          className="max-w-full max-h-[50vh] object-contain rounded-lg shadow-lg"
                        />
                        <p className="text-text-dim text-xs mt-2">Panel #{panelIndex + 1} — {panel.caption || '(no caption)'}</p>
                      </>
                    ) : (
                      <div className="text-center text-text-dim text-sm py-12">
                        <p>No image generated yet.</p>
                      </div>
                    )}

                    <div className="mt-3 flex gap-2">
                      <Button
                        variant="primary"
                        onClick={handleRegenerate}
                        disabled={isRegenerating}
                        size="sm"
                      >
                        {isRegenerating ? (
                          <span className="flex items-center gap-1">
                            <Spinner size="sm" />
                            Generating...
                          </span>
                        ) : (
                          '🔄 Regenerate'
                        )}
                      </Button>
                    </div>
                  </div>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}