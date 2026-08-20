// @vitest-environment node

import { describe, expect, it } from 'vitest';
import viteConfig from './vite.config';

const BACKEND_TARGET = 'http://127.0.0.1:8000';

describe('vite dev server proxy', () => {
  const proxy = viteConfig.server?.proxy;

  it('proxies /summary to the FastAPI backend', () => {
    const summary = proxy?.['/summary'] as { target?: string; changeOrigin?: boolean } | undefined;
    expect(summary?.target).toBe(BACKEND_TARGET);
    expect(summary?.changeOrigin).toBe(true);
  });

  it.each(['/devices', '/experiments', '/artifacts'])(
    'keeps %s pointed at the FastAPI backend',
    (key) => {
      const rule = proxy?.[key] as { target?: string; changeOrigin?: boolean } | undefined;
      expect(rule?.target).toBe(BACKEND_TARGET);
      expect(rule?.changeOrigin).toBe(true);
    },
  );
});
