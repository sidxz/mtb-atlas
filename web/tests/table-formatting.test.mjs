import assert from 'node:assert/strict';
import test from 'node:test';
import { numericValue, matches, scaleRanges, position, scaleColor, cellFormatting, parsePreferences } from '../src/table-formatting.ts';

const rule = { id: 'r', column: 'value', operator: 'gte', value: 0, upper: null, target: 'cell', color: 'green' };
const scale = { id: 's', column: 'value', palette: 'blue', mode: 'scale', minimum: null, maximum: null };

test('zeros and negative numbers are measurements; missing and non-finite values are not', () => {
  assert.equal(numericValue({ value: 0 }, 'value'), 0);
  assert.equal(numericValue({ value: -12 }, 'value'), -12);
  assert.equal(numericValue({ best_drug_phase: -1 }, 'best_drug_phase'), undefined);
  assert.equal(numericValue({ best_drug_phase: 4 }, 'best_drug_phase'), 4);
  for (const value of [null, undefined, NaN, Infinity, '0', false]) assert.equal(numericValue({ value }, 'value'), undefined);
  assert.equal(matches(undefined, rule), false);
  assert.equal(matches(0, rule), true);
  assert.equal(matches(-1, rule), false);
});

test('comparison operators and inclusive between boundaries', () => {
  for (const [operator, value, expected] of [['gt', 0, false], ['gte', 0, true], ['lt', -1, true], ['lte', 0, true], ['eq', 0, true], ['eq', 1, false]]) {
    assert.equal(matches(value, { ...rule, operator }), expected);
  }
  for (const [value, expected] of [[-2, false], [-1, true], [0, true], [1, true], [2, false]]) {
    assert.equal(matches(value, { ...rule, operator: 'between', value: -1, upper: 1 }), expected);
  }
});

test('automatic scales include every supplied row and exclude missing values', () => {
  const rows = Array.from({ length: 200 }, (_, value) => ({ value: 0 - value }));
  const ranges = scaleRanges([...rows, { value: null }, { value: Infinity }], [scale]);
  assert.equal(ranges[0].min, -199);
  assert.equal(ranges[0].max, 0);
  assert.deepEqual(scaleRanges([{ value: null }], [scale]), []);
  const fixed = scaleRanges(rows, [{ ...scale, minimum: 0, maximum: 100 }])[0];
  assert.equal(fixed.min, 0); assert.equal(fixed.max, 100);
});

test('normalization handles clipping, constant columns and extreme finite values', () => {
  assert.equal(position(-10, -10, 0), 0);
  assert.equal(position(-5, -10, 0), .5);
  assert.equal(position(5, -10, 0), 1);
  assert.equal(position(-100, -10, 0), 0);
  assert.equal(position(7, 7, 7), .5);
  assert.equal(position(0, -Number.MAX_VALUE, Number.MAX_VALUE), .5);
  assert.equal(scaleColor('red_green', 0), 'rgb(239, 68, 68)');
  assert.equal(scaleColor('red_green', .5), 'rgb(250, 204, 21)');
  assert.equal(scaleColor('red_green', 1), 'rgb(34, 197, 94)');
});

test('cell rules beat scales, scales beat row rules, and first matching rule wins', () => {
  const row = { value: 5, other: 10 };
  const ranges = scaleRanges([row], [scale]);
  const rowRule = { ...rule, target: 'row', color: 'red' };
  assert.match(cellFormatting(row, 'value', [rowRule, rule], ranges).backgroundColor, /#16a34a/);
  assert.match(cellFormatting(row, 'value', [rowRule], ranges).backgroundColor, /rgb\(/);
  assert.match(cellFormatting(row, 'other', [rowRule], ranges).backgroundColor, /#ef4444/);
  assert.match(cellFormatting(row, 'value', [{ ...rule, color: 'purple' }, rule], []).backgroundColor, /#a855f7/);
  assert.equal(cellFormatting({ value: null }, 'value', [rule], ranges), undefined);
});

test('data bars retain values and show bounded positions', () => {
  const ranges = scaleRanges([{ value: 0 }, { value: 100 }], [{ ...scale, mode: 'bar' }]);
  const row = { value: 25 };
  assert.match(cellFormatting(row, 'value', [], ranges).backgroundImage, /25%/);
  assert.equal(row.value, 25);
  assert.match(cellFormatting({ value: 200 }, 'value', [], ranges).backgroundImage, /100%/);
});

test('browser preferences reject corrupt rules and keep the identity column', () => {
  const parse = raw => parsePreferences(raw, ['rv_id', 'value'], ['value']);
  assert.deepEqual(parse(null), { visible: null, rules: [], scales: [] });
  assert.deepEqual(parse({ visible: ['missing', 'value', 'value'], rules: [rule], scales: [scale] }), { visible: ['rv_id', 'value'], rules: [rule], scales: [scale] });
  assert.deepEqual(parse({ visible: [], rules: [null], scales: [{ ...scale, minimum: 10, maximum: 2 }] }), { visible: ['rv_id'], rules: [], scales: [] });
  assert.deepEqual(parse({ rules: [{ ...rule, operator: 'constructor' }], scales: [{ ...scale, column: 'missing' }] }).rules, []);
  assert.deepEqual(parse({ rules: [{ ...rule, value: Infinity }], scales: [{ ...scale, minimum: 0, maximum: null }] }).scales, []);
});


test('clinical tables retain their own identity columns and skip unknown phases', () => {
  for (const [identity, phase] of [['pref_name', 'max_phase_tb'], ['nct_id', 'phase_max']]) {
    const settings = parsePreferences({ visible: [phase], rules: [], scales: [] }, [identity, phase], [phase], identity);
    assert.deepEqual(settings.visible, [identity, phase]);
    assert.equal(numericValue({ [phase]: -1 }, phase), undefined);
    assert.equal(numericValue({ [phase]: 0 }, phase), 0);
    const ranges = scaleRanges([{ [phase]: -1 }, { [phase]: null }, { [phase]: 2 }, { [phase]: 4 }], [{ ...scale, column: phase }]);
    assert.equal(ranges[0].min, 2);
    assert.equal(ranges[0].max, 4);
  }
});
