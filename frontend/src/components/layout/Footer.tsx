/**
 * Footer - Page footer with attribution.
 * 
 * Purpose: Display simple footer with technology credits (SDXL Lightning, Qwen, ROCm).
 * 
 * Used by: AppLayout
 */
import React from 'react';

export function Footer() {
  return (
    <div className="footer text-center py-5 text-text-dim text-xs">
      Powered by SDXL Lightning + Qwen 2.5 · AMD ROCm
    </div>
  );
}