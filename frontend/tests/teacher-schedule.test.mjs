import assert from 'node:assert/strict';
import { buildViewerWeeks } from '../src/lib/schedule.ts';

const teacher = { type: 'person', id: '123', label: 'Преподаватель' };
const events = [
  { date: '2026.10.19', beginLesson: '08:00', endLesson: '09:30', discipline: 'Алгебра', group: 'ФИТ-242', subGroup: 'ФИТ-242/1' },
  { date: '2026.10.19', beginLesson: '08:00', endLesson: '09:30', discipline: 'Алгебра', group: 'ФИТ-242', subGroup: 'ФИТ-242/2' },
  { date: '2026.10.19', beginLesson: '09:40', endLesson: '11:10', discipline: 'Геометрия', group: 'МО-241' }
];
const [week] = buildViewerWeeks('2026-10-19', '2026-10-19', [teacher], new Map([['person:123', events]]));
const first = week.rows[0].cells[0].lanes[0].lessons;
assert.equal(first.length, 2);
assert.deepEqual(first.map((lesson) => lesson.subgroup), ['ФИТ-242/1', 'ФИТ-242/2']);
assert.equal(week.rows[1].cells[0].lanes[0].lessons[0].discipline, 'Геометрия');
assert.equal(week.rows[0].cells[1].outOfRange, true);
console.log('Teacher schedule keeps parallel subgroup lessons and period boundaries');
