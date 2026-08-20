// @vitest-environment node

import { describe, expect, it } from 'vitest';
import viteConfig from './vite.config';

const BACKEND_TARGET = 'http://127.0.0.1:8000';

describe('vite dev server proxy', () => {
  const proxy = viteConfig.server?.proxy;

  it('proxies /api to the FastAPI backend', () => {
    const rule = proxy?.['/api'] as { target?: string; changeOrigin?: boolean } | undefined;
    expect(rule?.target).toBe(BACKEND_TARGET);
    expect(rule?.changeOrigin).toBe(true);
  });

  it.each(['/api/summary', '/api/devices', '/api/experiments', '/api/artifacts'])(
    'forwards %s through the /api proxy',
    (key) => {
      const rule = proxy?.['/api'] as { target?: string; changeOrigin?: boolean } | undefined;
      expect(rule?.target).toBe(BACKEND_TARGET);
      expect(rule?.changeOrigin).toBe(true);
    },
  );
});
