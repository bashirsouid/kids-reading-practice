/**
 * WizardNav - Navigation buttons for wizard flow.
 * 
 * Purpose: Provide consistent Back/Next navigation across all wizard pages.
 * Supports custom labels and next button disabled state.
 * 
 * Used by: StoryContentPage, StyleReferencePage, PanelBreakdownPage, PanelImagesPage, ReviewPage
 */
import React from 'react';
import { Button } from './Button';

interface WizardNavProps {
  onBack?: () => void;
  onNext?: () => void;
  nextDisabled?: boolean;
  backLabel?: string;
  nextLabel?: string;
}

export function WizardNav({ 
  onBack, 
  onNext, 
  nextDisabled = false,
  backLabel = '← Back',
  nextLabel = 'Next →'
}: WizardNavProps) {
  return (
    <div className="flex gap-2 mt-6">
      {onBack && (
        <Button variant="secondary" onClick={onBack} className="flex-1">
          {backLabel}
        </Button>
      )}
      {onNext && (
        <Button variant="primary" onClick={onNext} disabled={nextDisabled} className="flex-1">
          {nextLabel}
        </Button>
      )}
    </div>
  );
}