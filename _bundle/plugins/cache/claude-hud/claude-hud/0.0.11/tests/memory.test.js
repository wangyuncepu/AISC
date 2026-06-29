import { test } from 'node:test';
import assert from 'node:assert/strict';
import { _setMemoryReaderForTests, formatBytes, getMemoryUsage } from '../dist/memory.js';

test('getMemoryUsage returns coarse system RAM usage with clamped values', async () => {
  _setMemoryReaderForTests(() => ({
    totalBytes: 16 * 1024 ** 3,
    freeBytes: 20 * 1024 ** 3,
  }));

  const memoryUsage = await getMemoryUsage();

  assert.deepEqual(memoryUsage, {
    totalBytes: 16 * 1024 ** 3,
    usedBytes: 0,
    freeBytes: 16 * 1024 ** 3,
    usedPercent: 0,
  });
});

test('getMemoryUsage returns null when memory lookup fails', async () => {
  _setMemoryReaderForTests(() => {
    throw new Error('boom');
  });

  const memoryUsage = await getMemoryUsage();

  assert.equal(memoryUsage, null);
});

test('formatBytes formats human-readable units for memory line display', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1536), '1.5 KB');
  assert.equal(formatBytes(10 * 1024 ** 3), '10 GB');
});

test.after(() => {
  _setMemoryReaderForTests(null);
});
