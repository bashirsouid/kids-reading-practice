/**
 * Tests for UI Components
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../Button';
import { Card } from '../Card';
import { ProgressBar } from '../ProgressBar';

describe('Button', () => {
  it('renders children correctly', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('applies primary variant by default', () => {
    render(<Button>Primary</Button>);
    const button = screen.getByRole('button');
    expect(button.className).toContain('from-accent');
  });

  it('applies secondary variant', () => {
    render(<Button variant="secondary">Secondary</Button>);
    const button = screen.getByRole('button');
    expect(button.className).toContain('border-white/10');
  });

  it('handles click events', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click</Button>);
    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('can be disabled', () => {
    render(<Button disabled>Disabled</Button>);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
  });
});

describe('Card', () => {
  it('renders children correctly', () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText('Card content')).toBeInTheDocument();
  });

  it('handles click when onClick provided', () => {
    const handleClick = vi.fn();
    render(<Card onClick={handleClick}>Clickable</Card>);
    fireEvent.click(screen.getByText('Clickable'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});

describe('ProgressBar', () => {
  it('renders with correct width', () => {
    render(<ProgressBar percent={50} />);
    const progressBar = document.querySelector<HTMLElement>('.bg-gradient-to-r');
    expect(progressBar?.style.width).toBe('50%');
  });

  it('clamps values to 0-100', () => {
    const { rerender } = render(<ProgressBar percent={150} />);
    const progressBar = document.querySelector<HTMLElement>('.bg-gradient-to-r');
    expect(progressBar?.style.width).toBe('100%');

    rerender(<ProgressBar percent={-10} />);
    expect(progressBar?.style.width).toBe('0%');
  });

  it('shows label when provided', () => {
    render(<ProgressBar percent={25} label="Loading..." />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });
});
