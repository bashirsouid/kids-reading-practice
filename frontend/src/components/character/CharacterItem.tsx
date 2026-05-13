/**
 * CharacterItem - Individual character editor component.
 * 
 * Purpose: Display and edit a single character with name and description fields.
 * Includes remove button for deleting characters.
 * 
 * Used by: CharacterList
 */
import React from 'react';
import { Character } from '../../../types/wizard';
import { Button } from '../ui/Button';

interface CharacterItemProps {
  character: Character;
  index: number;
  onUpdate: (index: number, field: 'name' | 'description', value: string) => void;
  onRemove: (index: number) => void;
}

export function CharacterItem({ character, index, onUpdate, onRemove }: CharacterItemProps) {
  return (
    <div className="bg-surface2 p-3 rounded-lg mb-2">
      <div className="flex justify-between items-center mb-2">
        <span className="font-semibold text-gold text-sm">{character.name}</span>
        <Button
          variant="secondary"
          size="sm"
          className="px-2 py-0.5"
          onClick={() => onRemove(index)}
        >
          ✕
        </Button>
      </div>
      <input
        type="text"
        value={character.description}
        placeholder="Character description..."
        onChange={(e) => onUpdate(index, 'description', e.target.value)}
        className="w-full px-2 py-1 bg-bg border border-white/10 rounded text-text text-sm focus:outline-none focus:border-accent"
      />
    </div>
  );
}