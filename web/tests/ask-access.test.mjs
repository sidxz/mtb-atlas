import assert from 'node:assert/strict';
import test from 'node:test';
import { allowanceLabel, refusalMessage, captchaUnavailableMessage } from '../src/askAccess.ts';

const anon = { orcid: null, limits: true, remaining: 3, limit: 5, window: '1h', global_remaining: 400, turnstile_site_key: 'k', signin_available: true };
const at = new Date('2026-10-12T10:00:00');

test('the allowance reads as a count of what is left', () => {
  assert.equal(allowanceLabel(anon), '3 of 5 left this hour');
  assert.equal(allowanceLabel({ ...anon, orcid: '0000-0002-1825-0097', limit: 20, remaining: 20, window: '24h' }), '20 of 20 left today');
  assert.equal(allowanceLabel({ ...anon, limits: false }), null);
  assert.equal(allowanceLabel({ ...anon, remaining: null }), null);
});

test('a refusal is a sentence that names whose limit it is, never [object Object]', () => {
  const ip = refusalMessage({ limit: 'ip', retry_after: 600 }, at);
  assert.match(ip, /5 questions an hour/);
  assert.match(ip, /ORCID/);
  assert.match(refusalMessage({ limit: 'orcid', retry_after: 60 }, at), /20 questions for today/);
  const global = refusalMessage({ limit: 'global', retry_after: 60 }, at);
  assert.match(global, /across everyone/);
  assert.doesNotMatch(global, /your/i);
  for (const odd of [undefined, null, 'Service unavailable', { nonsense: true }]) {
    const message = refusalMessage(odd, at);
    assert.equal(typeof message, 'string');
    assert.doesNotMatch(message, /object Object/);
  }
});

test('a blocked CAPTCHA explains itself and offers ORCID when there is one', () => {
  assert.match(captchaUnavailableMessage(true), /ORCID/);
  assert.doesNotMatch(captchaUnavailableMessage(false), /ORCID/);
});
