export type ApiItem = Record<string, unknown>;
export type SearchItem = { id: string; label: string; description: string };
export type Group = SearchItem;
export type Slot = { number: number; start: string; end: string };
export type CommissionAvailability = { person: SearchItem; available: boolean; reason: 'free' | 'busy' | 'no-lessons' | 'load-error' };
export type CommissionOptions = { people: SearchItem[]; events: Map<string, ApiItem[]>; failedIds: Set<string>; mercy: boolean };
export type Cell = { key: string; date: string; available: boolean; teacherBusy: boolean; freeGroups: Group[]; lessons: string[]; outOfRange: boolean; commission: CommissionAvailability[] };
export type Week = { monday: string; saturday: string; dates: string[]; rows: { slot: Slot; cells: Cell[] }[] };

export const SLOTS: Slot[] = [
  { number: 1, start: '08:00', end: '09:30' },
  { number: 2, start: '09:40', end: '11:10' },
  { number: 3, start: '11:35', end: '13:05' },
  { number: 4, start: '13:15', end: '14:45' },
  { number: 5, start: '15:10', end: '16:40' },
  { number: 6, start: '16:50', end: '18:20' },
  { number: 7, start: '18:30', end: '20:00' },
  { number: 8, start: '20:10', end: '21:40' }
];

const API = '/api';
const militaryWords = ['военн', 'военная кафедра', 'военный учебный центр', 'вуц'];
const datePattern = /(?<!\d)(\d{4}[.-]\d{2}[.-]\d{2}|\d{2}[.-]\d{2}[.-]\d{4})(?!\d)/;
const timePattern = /(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?!\d)/;

function unwrapList(payload: unknown): ApiItem[] {
  if (Array.isArray(payload)) return payload.filter(isRecord);
  if (isRecord(payload)) {
    for (const key of ['data', 'items', 'results', 'schedule', 'lessons']) {
      if (Array.isArray(payload[key])) return (payload[key] as unknown[]).filter(isRecord);
    }
    for (const value of Object.values(payload)) {
      if (Array.isArray(value) && value.every(isRecord)) return value;
    }
  }
  throw new Error('Сервис расписания вернул данные в неизвестном формате.');
}

function isRecord(value: unknown): value is ApiItem {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function getJson(path: string, signal?: AbortSignal): Promise<ApiItem[]> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error('Не удалось связаться с расписанием ОмГТУ. Проверьте соединение и работу сервера сайта.');
  }
  if (!response.ok) throw new Error(`Сервис расписания вернул ошибку ${response.status}. Попробуйте позже.`);
  try {
    return unwrapList(await response.json());
  } catch {
    throw new Error('Не удалось прочитать ответ сервиса расписания.');
  }
}

export async function search(term: string, type: 'person' | 'group', signal?: AbortSignal): Promise<SearchItem[]> {
  const params = new URLSearchParams({ term, type });
  const data = await getJson(`/search?${params}`, signal);
  return data.flatMap((item) => {
    const id = item.id ?? item.oid ?? item.OID;
    if (id === undefined || id === null || id === '') return [];
    return [{
      id: String(id),
      label: String(item.label ?? item.name ?? item.title ?? item.description ?? id),
      description: String(item.description ?? '')
    }];
  });
}

export async function getSchedule(type: 'person' | 'group', id: string, start: string, finish: string, signal?: AbortSignal): Promise<ApiItem[]> {
  const params = new URLSearchParams({ start: start.replaceAll('-', '.'), finish: finish.replaceAll('-', '.'), lng: '1' });
  return getJson(`/schedule/${type}/${encodeURIComponent(id)}?${params}`, signal);
}

function parseDate(value: unknown): string | null {
  const match = String(value ?? '').match(datePattern)?.[1];
  if (!match) return null;
  const parts = match.split(/[.-]/);
  const iso = parts[0].length === 4 ? parts.join('-') : [parts[2], parts[1], parts[0]].join('-');
  const date = new Date(`${iso}T12:00:00`);
  return Number.isNaN(date.getTime()) || toIso(date) !== iso ? null : iso;
}

function parseTime(value: unknown): number | null {
  const match = String(value ?? '').match(timePattern);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function stringsIn(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(stringsIn);
  if (isRecord(value)) return Object.values(value).flatMap(stringsIn);
  return [];
}

function slotEvents(events: ApiItem[], slot: Slot): ApiItem[] {
  const slotStart = parseTime(slot.start)!;
  const slotEnd = parseTime(slot.end)!;
  return events.filter((event) => {
    const text = stringsIn(event).join(' ').toLowerCase();
    if (militaryWords.some((word) => text.includes(word))) return true;
    const start = ['beginLesson', 'startTime', 'timeStart', 'begin', 'start'].map((key) => parseTime(event[key])).find((value) => value !== null);
    const end = ['endLesson', 'endTime', 'timeEnd', 'finish', 'end'].map((key) => parseTime(event[key])).find((value) => value !== null);
    if (start == null || end == null || end <= start) return true;
    return start < slotEnd && slotStart < end;
  });
}

function isBusy(events: ApiItem[], slot: Slot): boolean { return slotEvents(events, slot).length > 0; }

function lessonLabel(event: ApiItem): string {
  const discipline = String(event.discipline ?? event.disciplineName ?? event.subject ?? event.name ?? 'Занятие');
  const group = String(event.group ?? event.groupName ?? '').trim();
  return group ? `${discipline} · ${group}` : discipline;
}

function indexEvents(events: ApiItem[]): { byDate: Map<string, ApiItem[]>; unknownDates: number } {
  const byDate = new Map<string, ApiItem[]>();
  let unknownDates = 0;
  for (const event of events) {
    const date = ['date', 'lessonDate', 'day', 'startDate'].map((key) => parseDate(event[key])).find(Boolean);
    if (!date) { unknownDates++; continue; }
    byDate.set(date, [...(byDate.get(date) ?? []), event]);
  }
  return { byDate, unknownDates };
}

export function toIso(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function fromIso(iso: string): Date { return new Date(`${iso}T12:00:00`); }
function addDays(date: Date, count: number): Date { const next = new Date(date); next.setDate(next.getDate() + count); return next; }

export function formatDate(iso: string, options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' }): string {
  return new Intl.DateTimeFormat('ru-RU', options).format(fromIso(iso));
}

export function buildWeeks(start: string, finish: string, teacherEvents: ApiItem[], groupEvents: Map<string, ApiItem[]>, groups: Group[], commissionOptions?: CommissionOptions, mode: 'availability' | 'substitution' | 'meeting' = 'availability'): { weeks: Week[]; unknownDates: number } {
  const teacher = indexEvents(teacherEvents);
  const indexedGroups = new Map(groups.map((group) => [group.id, indexEvents(groupEvents.get(group.id) ?? [])]));
  const indexedCommission = new Map(commissionOptions?.people.map((person) => [person.id, indexEvents(commissionOptions.events.get(person.id) ?? [])]) ?? []);
  const unknownDates = teacher.unknownDates + [...indexedGroups.values(), ...indexedCommission.values()].reduce((sum, item) => sum + item.unknownDates, 0);
  const startDate = fromIso(start);
  const monday = addDays(startDate, -((startDate.getDay() + 6) % 7));
  const weeks: Week[] = [];
  for (let weekStart = monday; toIso(weekStart) <= finish; weekStart = addDays(weekStart, 7)) {
    const dates = Array.from({ length: 6 }, (_, i) => toIso(addDays(weekStart, i)));
    weeks.push({
      monday: dates[0], saturday: dates[5], dates,
      rows: SLOTS.map((slot) => ({
        slot,
        cells: dates.map((date) => {
          const outOfRange = date < start || date > finish;
          const matchedLessons = outOfRange ? [] : slotEvents(teacher.byDate.get(date) ?? [], slot);
          const teacherBusy = matchedLessons.length > 0;
          const lessons = [...new Set(matchedLessons.map(lessonLabel))];
          const freeGroups = outOfRange || teacherBusy ? [] : groups.filter((group) => !isBusy(indexedGroups.get(group.id)?.byDate.get(date) ?? [], slot));
          const commission: CommissionAvailability[] = outOfRange ? [] : (commissionOptions?.people.map((person) => {
            const dailyEvents = indexedCommission.get(person.id)?.byDate.get(date) ?? [];
            const reason = commissionOptions.failedIds.has(person.id) ? 'load-error' : commissionOptions.mercy && dailyEvents.length === 0 ? 'no-lessons' : isBusy(dailyEvents, slot) ? 'busy' : 'free';
            return { person, available: reason === 'free', reason };
          }) ?? []);
          const available = !outOfRange && (mode === 'meeting' ? commission.length > 0 && commission.every((entry) => entry.available) : mode === 'substitution' ? teacherBusy : !teacherBusy && freeGroups.length > 0);
          return { key: `${date}-${slot.number}`, date, available, teacherBusy, freeGroups, lessons, outOfRange, commission };
        })
      }))
    });
  }
  return { weeks, unknownDates };
}
