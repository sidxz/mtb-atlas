import assert from 'node:assert/strict';
import test from 'node:test';
import { allowanceLabel, refusalMessage, captchaUnavailableMessage, questionDestination, signInOffer } from '../src/askAccess.ts';

const allowances = { anonymous_per_hour: 5, signed_in_per_day: 20, global_per_day: 500 };
const anon = { orcid: null, limits: true, remaining: 3, limit: 5, window: '1h', global_remaining: 400, turnstile_site_key: 'k', signin_available: true, allowances };
const at = new Date('2026-10-12T10:00:00');

test('the allowance reads as a count of what is left', () => {
  assert.equal(allowanceLabel(anon), '3 of 5 left this hour');
  assert.equal(allowanceLabel({ ...anon, orcid: '0000-0002-1825-0097', limit: 20, remaining: 20, window: '24h' }), '20 of 20 left today');
  assert.equal(allowanceLabel({ ...anon, limits: false }), null);
  assert.equal(allowanceLabel({ ...anon, remaining: null }), null);
});

test('a refusal is a sentence that names whose limit it is, never [object Object]', () => {
  const ip = refusalMessage({ limit: 'ip', retry_after: 600 }, at, anon);
  assert.match(ip, /5 questions an hour/);
  assert.match(ip, /ORCID for 20 a day/);
  assert.match(refusalMessage({ limit: 'orcid', retry_after: 60 }, at, anon), /20 questions for today/);
  const global = refusalMessage({ limit: 'global', retry_after: 60 }, at, anon);
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

test('the sentences use the allowances this deployment set, not the defaults', () => {
  const tight = { ...anon, allowances: { anonymous_per_hour: 2, signed_in_per_day: 8, global_per_day: 120 } };
  const ip = refusalMessage({ limit: 'ip', retry_after: 60 }, at, tight);
  assert.match(ip, /2 questions an hour/);
  assert.match(ip, /ORCID for 8 a day/);
  assert.match(refusalMessage({ limit: 'orcid', retry_after: 60 }, at, tight), /8 questions for today/);
  assert.match(refusalMessage({ limit: 'global', retry_after: 60 }, at, tight), /120 questions for today/);
  assert.equal(signInOffer(tight), 'Sign in with ORCID for 8 a day');
});

test('without knowing the numbers a refusal still makes sense and offers nothing false', () => {
  const ip = refusalMessage({ limit: 'ip', retry_after: 60 }, at, null);
  assert.doesNotMatch(ip, /\d+ questions/);
  assert.doesNotMatch(ip, /ORCID/);
  assert.doesNotMatch(refusalMessage({ limit: 'ip', retry_after: 60 }, at, { ...anon, signin_available: false }), /ORCID/);
  assert.equal(signInOffer(null), 'Sign in with ORCID');
});

test('the privacy wording names where this deployment sends a question', () => {
  const site = (llm) => ({ counts: {}, sources: [], caveats: [], site: { operator: null, contact: null, footer_links: [], llm } });
  assert.equal(questionDestination(site({ provider: 'anthropic', label: 'Anthropic', model: 'claude-haiku-5-5' })), 'Anthropic');
  assert.equal(questionDestination(site({ provider: 'ollama', label: 'a model run by the operator of this site', model: 'qwen3' })), 'a model run by the operator of this site');
  assert.equal(questionDestination(site(null)), 'the model service this site is configured with');
  assert.equal(questionDestination(null), 'the model service this site is configured with');
});
