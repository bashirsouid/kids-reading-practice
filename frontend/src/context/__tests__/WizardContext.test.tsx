/**
  * Tests for WizardContext
  */
 import { describe, it, expect } from 'vitest';
 import { renderHook, act } from '@testing-library/react';
 import { WizardProvider, useWizard } from '../../context/WizardContext';

describe('WizardContext', () => {
  it('should provide initial state', () => {
    const { result } = renderHook(() => useWizard(), {
      wrapper: ({ children }) => <WizardProvider>{children}</WizardProvider>,
    });

    expect(result.current.state.page).toBe('home');
    expect(result.current.state.mode).toBe('random');
    expect(result.current.state.modelStatus).toBe('loading');
  });

  it('should set mode', () => {
    const { result } = renderHook(() => useWizard(), {
      wrapper: ({ children }) => <WizardProvider>{children}</WizardProvider>,
    });

    act(() => {
      result.current.dispatch({ type: 'SET_MODE', payload: 'custom' });
    });

    expect(result.current.state.mode).toBe('custom');
  });

  it('should set job ID', () => {
    const { result } = renderHook(() => useWizard(), {
      wrapper: ({ children }) => <WizardProvider>{children}</WizardProvider>,
    });

    act(() => {
      result.current.dispatch({ type: 'SET_JOB_ID', payload: 'test-job-123' });
    });

    expect(result.current.state.jobId).toBe('test-job-123');
  });

  it('should reset state', () => {
    const { result } = renderHook(() => useWizard(), {
      wrapper: ({ children }) => <WizardProvider>{children}</WizardProvider>,
    });

    act(() => {
      result.current.dispatch({ type: 'SET_MODE', payload: 'fullstory' });
      result.current.dispatch({ type: 'SET_JOB_ID', payload: 'job-123' });
    });

    act(() => {
      result.current.dispatch({ type: 'RESET' });
    });

    expect(result.current.state.mode).toBe('random');
    expect(result.current.state.jobId).toBe(null);
  });
});