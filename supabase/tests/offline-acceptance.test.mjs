import test from 'node:test';
import assert from 'node:assert/strict';
import { runAcceptance } from './offline-acceptance.mjs';

test('offline acceptance exercises coordinator, RPC adapter, real SQL and vault', {timeout:30_000}, async () => {
  const report = await runAcceptance();
  assert.equal(report.schema, 'crier.webull-offline-acceptance.v1');
  assert.equal(report.deployment, 'not_deployed');
  assert.equal(report.brokerCalls, 0);
  assert.equal(report.discordCalls, 0);
  assert.equal(report.scenarios.length, 9);
  assert.ok(report.scenarios.every(scenario => scenario.status === 'passed'));
  assert.ok(report.capabilities.every(capability => capability.implemented && !capability.deployed && !capability.brokerAccepted));
  assert.match(report.sourceCommit, /^[a-f0-9]{40}$/);
  assert.equal(typeof report.sourceTreeDirty, 'boolean');
  assert.equal(report.evidenceAttribution, report.sourceTreeDirty ? 'working_tree' : 'commit');
  for (const secret of ['fixture-access', 'fixture-refresh', 'fixture-client-secret', 'fixture-identity']) {
    assert.ok(!JSON.stringify(report).includes(secret));
  }
});
