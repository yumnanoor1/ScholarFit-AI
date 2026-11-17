import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { env } from 'node:process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createServer } from 'vite';

const apiUrl = env.ADMIN_API_INTEGRATION_URL;

test('the actual Admin API client interoperates with the local FastAPI test server', {
  skip: !apiUrl,
}, async (t) => {
  const requiredValues = [
    'ADMIN_API_ADMIN_TOKEN',
    'ADMIN_API_STUDENT_TOKEN',
    'ADMIN_API_SERVER_ERROR_TOKEN',
  ];
  for (const name of requiredValues) {
    assert.ok(env[name], `${name} must be provided by the isolated Python harness`);
  }

  const projectRoot = resolve(fileURLToPath(new URL('../..', import.meta.url)));
  const envDir = mkdtempSync(join(tmpdir(), 'fitscholar-admin-api-vite-'));
  const previousApiUrl = env.VITE_API_BASE_URL;
  env.VITE_API_BASE_URL = apiUrl;
  let vite;

  try {
    vite = await createServer({
      configFile: false,
      root: projectRoot,
      envDir,
      server: { middlewareMode: true, hmr: false, ws: false, watch: null },
      optimizeDeps: { noDiscovery: true, include: [] },
      appType: 'custom',
      logLevel: 'silent',
    });
    const { adminApi } = await vite.ssrLoadModule('/src/services/adminApi.js');

    await t.test('an Admin token retrieves the real summary response', async () => {
      const summary = await adminApi.summary(env.ADMIN_API_ADMIN_TOKEN);
      assert.equal(typeof summary.total, 'number');
      assert.equal(typeof summary.verified, 'number');
      assert.equal(typeof summary.unverified, 'number');
    });

    await t.test('a request with no Authorization header is rejected', async () => {
      const response = await fetch(`${apiUrl}/admin/scholarships/summary`);
      assert.equal(response.status, 401);
    });

    await t.test('the client surfaces its missing-token request as unauthorized', async () => {
      await assert.rejects(adminApi.summary(undefined), (error) => {
        assert.equal(error.status, 401);
        return true;
      });
    });

    await t.test('an invalid token is rejected by FastAPI authentication', async () => {
      await assert.rejects(adminApi.summary('invalid-integration-token'), (error) => {
        assert.equal(error.status, 401);
        return true;
      });
    });

    await t.test('a valid student token is denied Admin access', async () => {
      await assert.rejects(
        adminApi.summary(env.ADMIN_API_STUDENT_TOKEN),
        (error) => {
          assert.equal(error.status, 403);
          return true;
        },
      );
    });

    await t.test('backend request validation errors reach the client', async () => {
      await assert.rejects(
        adminApi.create(env.ADMIN_API_ADMIN_TOKEN, {
          name: '',
          country: 'France',
        }),
        (error) => {
          assert.equal(error.status, 422);
          assert.match(error.message, /name/i);
          return true;
        },
      );
    });

    await t.test('a server-side failure status reaches the client', async () => {
      await assert.rejects(
        adminApi.summary(env.ADMIN_API_SERVER_ERROR_TOKEN),
        (error) => {
          assert.equal(error.status, 503);
          assert.equal(error.message, 'Test server unavailable');
          return true;
        },
      );
    });
  } finally {
    if (vite) await vite.close();
    if (previousApiUrl === undefined) {
      delete env.VITE_API_BASE_URL;
    } else {
      env.VITE_API_BASE_URL = previousApiUrl;
    }
    rmSync(envDir, { recursive: true, force: true });
  }
});
