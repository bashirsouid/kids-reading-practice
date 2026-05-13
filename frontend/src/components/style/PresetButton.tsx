/**
 * PresetButton - Art style preset button component.
 * 
 * Purpose: Display a compact preset style option with active state styling.
 * Shows gold accent when active, transparent border when inactive.
 * 
 * Used by: ArtStyleSelector
 */
import React from 'react';

interface PresetButtonProps {
  label: string;
  isActive: boolean;
  onClick: () => void;
}

export function PresetButton({ label, isActive, onClick }: PresetButtonProps) {
  return (
    <button
      className={`preset-btn px-1.5 py-1.5 text-xs border rounded-md cursor-pointer transition-all text-center ${
        isActive 
          ? 'border-gold bg-gold/20' 
          : 'border-white/10 bg-bg hover:border-gold hover:bg-gold/10'
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}