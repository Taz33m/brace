import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/story/schedule-review.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { reviewQuestions, reviewMoney, sourceLink } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const schedule = { property: { homes: 240, homes_on_record: 265, scan_date: null }, total: { lines: 12, lines_priced: 9 }, buildings: [{ units: [{ scan_id:'scan1', name:'One bedroom', rooms:[{name:'Kitchen',read:false,doubts:[{doubt:'Confirm cabinet count.'}]}] }] }] };
test('review exposes mismatched unit counts, missing prices, scan date and room evidence', () => {
 const q=reviewQuestions(schedule).join('\n');
 for (const value of ['240','265','3 unpriced','scan date is unavailable','room was not read','Confirm cabinet count','renovation package']) assert.ok(q.includes(value),value);
});
test('the same scan allocated twice does not duplicate its questions', () => {
 const copy=structuredClone(schedule); copy.buildings.push(copy.buildings[0]);
 assert.equal(reviewQuestions(copy).filter(q=>q.includes('Confirm cabinet count')).length,1);
});
test('missing prices remain unavailable and a real zero is preserved', () => {
 assert.equal(reviewMoney({low:null,high:null}),'Unpriced / unavailable');
 assert.equal(reviewMoney({low:0,high:0}),'$0');
 assert.equal(reviewMoney({low:1.7,high:3.2},2),'$1.70–$3.20');
 assert.equal(reviewMoney({low:100,high:200}),'$100–$200');
});
test('source links permit web evidence, never executable URLs', () => {
 assert.equal(sourceLink('javascript:alert(1)'),undefined);
 assert.equal(sourceLink('file:///etc/passwd'),undefined);
 assert.equal(sourceLink(null),undefined);
 assert.equal(sourceLink('https://example.org/price'),'https://example.org/price');
});
