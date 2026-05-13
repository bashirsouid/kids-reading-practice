/**
 * CharacterList - Container for multiple character editors.
 * 
 * Purpose: Display list of characters with add/remove functionality.
 * Shows placeholder message when no characters defined.
 * 
 * Used by: StyleReferencePage
 */
import React from 'react';
import { Character } from '../../../types/wizard';
import { CharacterItem } from './CharacterItem';
import { Button } from '../ui/Button';

interface CharacterListProps {
  characters: Character[];
  onUpdate: (index: number, field: 'name' | 'description', value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}

export function CharacterList({ characters, onUpdate, onAdd, onRemove }: CharacterListProps) {
  if (characters.length === 0) {
    return (
      <p className="text-text-dim text-sm">
        No characters defined yet. Characters will be extracted from your story.
      </p>
    );
  }

  return (
    <div>
      {characters.map((char, idx) => (
        <CharacterItem
          key={idx}
          character={char}
          index={idx}
          onUpdate={onUpdate}
          onRemove={onRemove}
        />
      ))}
      <Button variant="secondary" size="sm" onClick={onAdd}>
        ➕ Add Character
      </Button>
    </div>
  );
}