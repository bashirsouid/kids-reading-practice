/**
 * ModeSelector - Grid of 4 story mode options.
 * 
 * Purpose: Allow users to select story generation mode (random, themed, custom, fullstory).
 * Displays ModeCard components in a 4-column grid.
 * 
 * Used by: ComicInfoPage
 */
import React from 'react';
import { ModeCard } from './ModeCard';

interface ModeSelectorProps {
  selectedMode: string;
  onSelect: (mode: string) => void;
}

const MODES = [
  { mode: 'random', label: 'Random', description: 'Surprise me', emoji: '🎲' },
  { mode: 'themed', label: 'Themed', description: 'Pick a theme', emoji: '🎯' },
  { mode: 'custom', label: 'Custom', description: 'Write your own', emoji: '✍️' },
  { mode: 'fullstory', label: 'Full Story', description: 'Paste complete story', emoji: '📖' },
];

export function ModeSelector({ selectedMode, onSelect }: ModeSelectorProps) {
  return (
    <div className="mode-grid grid grid-cols-4 gap-2.5 mb-4">
      {MODES.map((m) => (
        <ModeCard
          key={m.mode}
          mode={m.mode}
          label={m.label}
          description={m.description}
          emoji={m.emoji}
          isActive={selectedMode === m.mode}
          onClick={() => onSelect(m.mode)}
        />
      ))}
    </div>
  );
}