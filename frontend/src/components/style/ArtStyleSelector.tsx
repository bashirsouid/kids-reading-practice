/**
 * ArtStyleSelector - Preset art styles + custom input component.
 * 
 * Purpose: Allow users to select from 12 preset art styles or enter custom style.
 * Updates selected style immediately on preset click or custom input change.
 * 
 * Used by: StyleReferencePage
 */
import React, { useState } from 'react';
import { PresetButton } from './PresetButton';

interface ArtStyleSelectorProps {
  selectedStyle: string;
  onSelect: (style: string) => void;
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

export function ArtStyleSelector({ selectedStyle, onSelect }: ArtStyleSelectorProps) {
  const [customStyle, setCustomStyle] = useState(selectedStyle);

  const handlePresetClick = (style: string) => {
    setCustomStyle(style);
    onSelect(style);
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setCustomStyle(value);
    onSelect(value);
  };

  return (
    <div>
      <div className="preset-buttons grid grid-cols-4 gap-1.5 mt-2">
        {PRESET_STYLES.map((style) => (
          <PresetButton
            key={style}
            label={style.split(' ').slice(0, 2).join(' ')}
            isActive={selectedStyle === style}
            onClick={() => handlePresetClick(style)}
          />
        ))}
      </div>
      <div className="mt-3">
        <input
          type="text"
          value={customStyle}
          onChange={handleCustomChange}
          placeholder="Or type a custom art style..."
          className="w-full px-3 py-2 bg-bg border border-white/10 rounded-md text-text text-sm focus:outline-none focus:border-accent"
        />
      </div>
    </div>
  );
}