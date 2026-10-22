export type ApiItem = Record<string, unknown>;
export type SearchItem = { id: string; label: string; description: string };
export type Group = SearchItem;
export type Slot = { number: number; start: string; end: string };
export type CommissionAvailability = { person: SearchItem; available: boolean; reason: 'free' | 'busy' | 'no-lessons' | 'load-error' };
export type CommissionOptions = { people: SearchItem[]; events: Map<string, ApiItem[]>; failedIds: Set<string>; mercy: boolean };
export type WindowStatus = 'none' | 'group-window' | 'teacher-window' | 'both-window';
export type UnavailableReason =
  | 'out-of-range'
  | 'teacher-busy'
  | 'group-busy'
  | 'both-busy'
  | 'teachers-busy'
  | 'auditorium-busy'
  | 'auditoriums-busy'
  | 'no-lesson';

export type Building = {
  buildingOid: number;
  name: string;
  abbr: string;
};

export type AuditoriumItem = {
  auditoriumOid: number;
  name: string;
  number: string;
  building: string;
  buildingOid: number;
  typeOfAuditorium: string;
  amount: number;
  computerEquipment?: number;
  mediaEquipment?: number;
};

export type AuditoriumSlotDetail = {
  auditorium: SearchItem;
  busy: boolean;
  lessons: string[];
  lessonDetails: LessonDetail[];
};

export type LessonDetail = {
  discipline: string;
  kindOfWork?: string;
  auditorium?: string;
  lecturer?: string;
  group?: string;
  label: string;
};

export type GroupSlotDetail = {
  group: Group;
  busy: boolean;
  hasWindow: boolean;
  lessons: string[];
  lessonDetails: LessonDetail[];
};

export type TeacherSlotDetail = {
  person: SearchItem;
  busy: boolean;
  hasWindow: boolean;
  available: boolean;
  reason: 'free' | 'busy' | 'no-lessons' | 'load-error';
  lessons: string[];
  lessonDetails: LessonDetail[];
};

export type Cell = {
  key: string;
  date: string;
  available: boolean;
  teacherBusy: boolean;
  teacherHasWindow: boolean;
  freeGroups: Group[];
  busyGroups: Group[];
  groupsDetails: GroupSlotDetail[];
  teachersDetails?: TeacherSlotDetail[];
  freeGroupsWithWindow?: string[];
  lessons: string[];
  lessonDetails: LessonDetail[];
  auditoriumsDetails?: AuditoriumSlotDetail[];
  freeAuditoriums?: SearchItem[];
  busyAuditoriums?: SearchItem[];
  auditoriumBusy?: boolean;
  outOfRange: boolean;
  commission: CommissionAvailability[];
  windowStatus: WindowStatus;
  unavailableReason?: UnavailableReason;
  unavailableText?: string;
};
export type DayColumnStatus = {
  date: string;
  dayIndex: number;
  outOfRange: boolean;
  teacherFreeDay: boolean;
  groupFreeDay: boolean;
  bothFreeDay: boolean;
  freeDayStatus: 'none' | 'teacher' | 'group' | 'both';
  badgeLabel?: string;
  tooltipText: string;
};

export type Week = {
  monday: string;
  saturday: string;
  dates: string[];
  daysStatus?: DayColumnStatus[];
  rows: { slot: Slot; cells: Cell[] }[];
};

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

export async function search(term: string, type: 'person' | 'group' | 'auditorium', signal?: AbortSignal): Promise<SearchItem[]> {
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

export async function getSchedule(type: 'person' | 'group' | 'auditorium', id: string, start: string, finish: string, signal?: AbortSignal): Promise<ApiItem[]> {
  const params = new URLSearchParams({ start: start.replaceAll('-', '.'), finish: finish.replaceAll('-', '.'), lng: '1' });
  return getJson(`/schedule/${type}/${encodeURIComponent(id)}?${params}`, signal);
}

export const DEFAULT_BUILDINGS: Building[] = [
  { buildingOid: 5, name: 'Главный корпус', abbr: 'Г' },
  { buildingOid: 10, name: 'УЛК-1', abbr: '1' },
  { buildingOid: 12, name: 'УЛК-2', abbr: '2' },
  { buildingOid: 13, name: 'УЛК-3', abbr: '3' },
  { buildingOid: 14, name: 'УЛК-4', abbr: '4' },
  { buildingOid: 15, name: 'УЛК-5', abbr: '5' },
  { buildingOid: 16, name: 'УЛК-6', abbr: '6' },
  { buildingOid: 17, name: 'УЛК-7', abbr: '7' },
  { buildingOid: 18, name: 'УЛК-8', abbr: '8' },
  { buildingOid: 19, name: 'УЛК-8б', abbr: '8б' },
  { buildingOid: 20, name: 'УЛК-9', abbr: '9' },
  { buildingOid: 22, name: 'УЛК-10', abbr: '10' },
  { buildingOid: 11, name: 'УЛК-11', abbr: '11' },
  { buildingOid: 34, name: 'УЛК-12', abbr: '12' },
  { buildingOid: 39, name: 'УЛК-13', abbr: '13' },
  { buildingOid: 37, name: 'УЛК-14', abbr: '14' },
  { buildingOid: 27, name: 'УПМ', abbr: 'УПМ' }
];

let cachedBuildings: Building[] | null = null;
export async function getBuildings(signal?: AbortSignal): Promise<Building[]> {
  if (cachedBuildings) return cachedBuildings;
  try {
    const items = await getJson('/dictionary/buildings', signal);
    const result = items.map((b) => ({
      buildingOid: Number(b.buildingOid),
      name: String(b.name ?? b.abbr ?? 'Корпус'),
      abbr: String(b.abbr ?? b.name ?? '')
    })).filter((b) => !isNaN(b.buildingOid) && b.name.trim().length > 0 && b.name !== 'Виртуальное');

    result.sort((a, b) => {
      const aIsUlk = a.name.startsWith('УЛК') || a.name.startsWith('Глав');
      const bIsUlk = b.name.startsWith('УЛК') || b.name.startsWith('Глав');
      if (aIsUlk && !bIsUlk) return -1;
      if (!aIsUlk && bIsUlk) return 1;
      return a.name.localeCompare(b.name, 'ru', { numeric: true });
    });
    cachedBuildings = result;
    return result;
  } catch (err) {
    console.warn('Failed to fetch buildings, using default list', err);
    return DEFAULT_BUILDINGS;
  }
}

const cachedAuditoriumsByBuilding = new Map<number, AuditoriumItem[]>();
let cachedAllAuditoriums: AuditoriumItem[] | null = null;

export async function getAuditoriums(buildingOid?: number, signal?: AbortSignal): Promise<AuditoriumItem[]> {
  if (buildingOid && cachedAuditoriumsByBuilding.has(buildingOid)) {
    return cachedAuditoriumsByBuilding.get(buildingOid)!;
  }
  if (!buildingOid && cachedAllAuditoriums) {
    return cachedAllAuditoriums;
  }

  const query = buildingOid ? `?buildingOid=${encodeURIComponent(buildingOid)}` : '';
  const items = await getJson(`/dictionary/auditoriums${query}`, signal);
  const result = items.map((a) => ({
    auditoriumOid: Number(a.auditoriumOid),
    name: String(a.name ?? a.number ?? ''),
    number: String(a.number ?? a.name ?? ''),
    building: String(a.building ?? ''),
    buildingOid: Number(a.buildingOid),
    typeOfAuditorium: String(a.typeOfAuditorium ?? ''),
    amount: Number(a.amount ?? 0),
    computerEquipment: Number(a.computerEquipment ?? 0),
    mediaEquipment: Number(a.mediaEquipment ?? 0)
  })).filter((a) => !isNaN(a.auditoriumOid) && a.name.trim().length > 0);

  if (buildingOid) {
    cachedAuditoriumsByBuilding.set(buildingOid, result);
  } else {
    cachedAllAuditoriums = result;
  }
  return result;
}

export async function getBuildingSchedule(buildingOid: number, start: string, finish: string, signal?: AbortSignal): Promise<ApiItem[]> {
  const params = new URLSearchParams({ start: start.replaceAll('-', '.'), finish: finish.replaceAll('-', '.'), lng: '1' });
  return getJson(`/schedule/building/${encodeURIComponent(buildingOid)}?${params}`, signal);
}

export const AUDITORIUM_TYPE_CATEGORIES = [
  { id: 'lecture', label: 'Лекционные', matches: ['лекцион'] },
  { id: 'classroom', label: 'Учебные аудитории', matches: ['учебная аудитория'] },
  { id: 'computer', label: 'Компьютерные классы', matches: ['компьютерн', 'комп.класс'] },
  { id: 'lab', label: 'Лаборатории', matches: ['лаборатор'] },
  { id: 'master', label: 'Магистерские / Проектные', matches: ['магистерск', 'проектирован'] }
];

export function matchesAuditoriumType(typeString: string, categoryIds: Set<string>): boolean {
  if (categoryIds.size === 0) return true;
  const lower = (typeString || '').toLowerCase();
  for (const catId of categoryIds) {
    const cat = AUDITORIUM_TYPE_CATEGORIES.find((c) => c.id === catId);
    if (cat && cat.matches.some((m) => lower.includes(m))) {
      return true;
    }
  }
  return false;
}

export type AuditoriumAvailabilityInfo = {
  auditorium: AuditoriumItem;
  freeAll: boolean;
  busySlotsCount: number;
  totalSlotsCount: number;
  busySlots: { date: string; slot: Slot; lessons: string[] }[];
};

export function checkAuditoriumsAvailability(
  auditoriums: AuditoriumItem[],
  buildingEvents: ApiItem[],
  selectedSlots: { date: string; slot: Slot }[]
): AuditoriumAvailabilityInfo[] {
  const audEventsMap = new Map<number, Map<string, ApiItem[]>>();
  for (const event of buildingEvents) {
    const audOid = Number(event.auditoriumOid);
    if (!audOid) continue;
    const date = parseDate(event.date);
    if (!date) continue;
    let byAud = audEventsMap.get(audOid);
    if (!byAud) {
      byAud = new Map();
      audEventsMap.set(audOid, byAud);
    }
    let daily = byAud.get(date);
    if (!daily) {
      daily = [];
      byAud.set(date, daily);
    }
    daily.push(event);
  }

  return auditoriums.map((aud) => {
    const byAud = audEventsMap.get(aud.auditoriumOid);
    const busySlots: { date: string; slot: Slot; lessons: string[] }[] = [];
    for (const { date, slot } of selectedSlots) {
      const daily = byAud?.get(date) ?? [];
      const evs = slotEvents(daily, slot);
      if (evs.length > 0) {
        busySlots.push({
          date,
          slot,
          lessons: [...new Set(evs.map(extractDiscipline))]
        });
      }
    }
    return {
      auditorium: aud,
      freeAll: busySlots.length === 0,
      busySlotsCount: busySlots.length,
      totalSlotsCount: selectedSlots.length,
      busySlots
    };
  });
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

function extractDiscipline(event: ApiItem): string {
  return String(event.discipline ?? event.disciplineName ?? event.subject ?? event.name ?? 'Занятие').trim();
}

function extractAuditorium(event: ApiItem): string | undefined {
  const raw = event.auditorium ?? event.auditoriumName ?? event.aud ?? event.room ?? event.classroom;
  if (raw == null) return undefined;
  const str = String(raw).trim();
  if (!str || str.toLowerCase() === 'null') return undefined;
  return str;
}

function extractLecturer(event: ApiItem): string | undefined {
  if (event.lecturer_title && String(event.lecturer_title).trim()) {
    return String(event.lecturer_title).trim();
  }
  if (event.lecturer && String(event.lecturer).trim()) {
    return String(event.lecturer).trim();
  }
  if (Array.isArray(event.listOfLecturers) && event.listOfLecturers.length > 0) {
    const first = event.listOfLecturers[0];
    if (isRecord(first)) {
      const name = first.lecturer_title ?? first.lecturer;
      if (name && String(name).trim()) return String(name).trim();
    }
  }
  const fallback = event.teacher ?? event.teacherName ?? event.person;
  if (fallback && String(fallback).trim()) return String(fallback).trim();
  return undefined;
}

function extractGroup(event: ApiItem): string | undefined {
  const raw = event.group ?? event.stream ?? event.subGroup ?? event.subgroup ?? event.groupName;
  if (raw == null) return undefined;
  const str = String(raw).trim();
  if (!str || str.toLowerCase() === 'null') return undefined;
  return str;
}

export function extractLessonDetail(event: ApiItem): LessonDetail {
  const discipline = extractDiscipline(event);
  const auditorium = extractAuditorium(event);
  const lecturer = extractLecturer(event);
  const group = extractGroup(event);
  const kindOfWork = event.kindOfWork ? String(event.kindOfWork).trim() : undefined;

  const parts = [discipline];
  if (auditorium) parts.push(`ауд. ${auditorium}`);
  if (lecturer) parts.push(formatShortName(lecturer));
  else if (group) parts.push(group);

  return {
    discipline,
    kindOfWork,
    auditorium,
    lecturer: lecturer ? formatShortName(lecturer) : undefined,
    group,
    label: parts.join(' · ')
  };
}

export function formatShortName(name?: string): string {
  if (!name) return '';
  const clean = name.trim();
  const withoutTitle = clean.replace(/^(доц\.|проф\.|асс\.|ст\.\s*преп\.|преп\.)\s+/i, '');
  const parts = withoutTitle.split(/\s+/);
  if (parts.length >= 3) {
    const p1 = parts[1].replace(/\./g, '');
    const p2 = parts[2].replace(/\./g, '');
    const i1 = p1.length > 0 ? `${p1[0]}.` : '';
    const i2 = p2.length > 0 ? `${p2[0]}.` : '';
    return `${parts[0]} ${i1}${i2}`;
  }
  if (parts.length === 2 && parts[1].length > 2 && !parts[1].includes('.')) {
    return `${parts[0]} ${parts[1][0]}.`;
  }
  return withoutTitle;
}

export function formatLessonKindShort(kind?: string): string {
  if (!kind) return '';
  const k = kind.trim().toLowerCase();
  if (k.startsWith('лек')) return 'Л';
  if (k.startsWith('пр') || k.includes('практ')) return 'ПЗ';
  if (k.startsWith('лаб')) return 'ЛР';
  return kind.slice(0, 3);
}

function lessonLabel(event: ApiItem): string {
  return extractLessonDetail(event).label;
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
export function addDays(date: Date, count: number): Date { const next = new Date(date); next.setDate(next.getDate() + count); return next; }

export function formatDate(iso: string, options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' }): string {
  return new Intl.DateTimeFormat('ru-RU', options).format(fromIso(iso));
}

export function hasWindowBefore(busySlots: number[], slotNumber: number): boolean {
  const earlier = busySlots.filter((s) => s < slotNumber);
  if (earlier.length === 0) return false;
  const last = Math.max(...earlier);
  return last < slotNumber - 1;
}

export function buildWeeks(
  start: string,
  finish: string,
  teacherEvents: ApiItem[],
  groupEvents: Map<string, ApiItem[]>,
  groups: Group[],
  commissionOptions?: CommissionOptions,
  mode: 'availability' | 'substitution' | 'meeting' = 'availability',
  selectedKeys?: Set<string>,
  auditoriumEvents?: Map<string, ApiItem[]>,
  auditoriums?: SearchItem[]
): { weeks: Week[]; unknownDates: number } {
  const teacher = indexEvents(teacherEvents);
  const indexedGroups = new Map(groups.map((group) => [group.id, indexEvents(groupEvents.get(group.id) ?? [])]));
  const indexedCommission = new Map(commissionOptions?.people.map((person) => [person.id, indexEvents(commissionOptions.events.get(person.id) ?? [])]) ?? []);
  const indexedAuditoriums = new Map((auditoriums ?? []).map((aud) => [aud.id, indexEvents(auditoriumEvents?.get(aud.id) ?? [])]));
  const unknownDates = teacher.unknownDates + [...indexedGroups.values(), ...indexedCommission.values(), ...indexedAuditoriums.values()].reduce((sum, item) => sum + item.unknownDates, 0);
  const startDate = fromIso(start);
  const monday = addDays(startDate, -((startDate.getDay() + 6) % 7));
  const weeks: Week[] = [];
  for (let weekStart = monday; toIso(weekStart) <= finish; weekStart = addDays(weekStart, 7)) {
    const dates = Array.from({ length: 6 }, (_, i) => toIso(addDays(weekStart, i)));

    const daysStatus: DayColumnStatus[] = dates.map((date, dayIndex) => {
      const outOfRange = date < start || date > finish;
      if (outOfRange) {
        return {
          date,
          dayIndex,
          outOfRange: true,
          teacherFreeDay: false,
          groupFreeDay: false,
          bothFreeDay: false,
          freeDayStatus: 'none',
          tooltipText: ''
        };
      }

      if (mode === 'meeting' && commissionOptions?.people && commissionOptions.people.length > 0) {
        const freeMeetingTeachers = commissionOptions.people.filter((p) => {
          const dailyEvents = indexedCommission.get(p.id)?.byDate.get(date) ?? [];
          return dailyEvents.length === 0;
        });
        const allMeetingFree = freeMeetingTeachers.length === commissionOptions.people.length;
        if (allMeetingFree) {
          const badgeLabel = commissionOptions.people.length === 2 ? 'Без пар у обоих' : 'Без пар у всех';
          const tooltipText = `У всех преподавателей (${commissionOptions.people.map((p) => p.label).join(', ')}) в этот день нет пар`;
          return {
            date,
            dayIndex,
            outOfRange: false,
            teacherFreeDay: false,
            groupFreeDay: false,
            bothFreeDay: true,
            freeDayStatus: 'both',
            badgeLabel,
            tooltipText
          };
        }
      }

      const teacherDailyEvents = teacher.byDate.get(date) ?? [];
      const teacherFreeDay = teacherEvents.length > 0 && teacherDailyEvents.length === 0;

      const freeGroupObjects = groups.filter((group) => {
        const dailyEvents = indexedGroups.get(group.id)?.byDate.get(date) ?? [];
        return dailyEvents.length === 0;
      });
      const allGroupsFree = groups.length > 0 && freeGroupObjects.length === groups.length;
      const groupFreeDay = allGroupsFree;
      const bothFreeDay = teacherFreeDay && groupFreeDay;

      const freeDayStatus: 'none' | 'teacher' | 'group' | 'both' = bothFreeDay
        ? 'both'
        : teacherFreeDay
        ? 'teacher'
        : groupFreeDay
        ? 'group'
        : 'none';

      let badgeLabel = '';
      let tooltipText = '';
      if (bothFreeDay) {
        badgeLabel = groups.length > 1 ? 'Без пар у всех' : 'Без пар у обоих';
        if (groups.length > 1) {
          tooltipText = `У преподавателя и всех групп (${freeGroupObjects.map((g) => g.label).join(', ')}) в этот день нет пар`;
        } else {
          tooltipText = `У преподавателя и группы (${freeGroupObjects.map((g) => g.label).join(', ')}) в этот день нет пар`;
        }
      } else if (teacherFreeDay) {
        badgeLabel = 'Без пар у преп.';
        if (freeGroupObjects.length > 0) {
          tooltipText = `У преподавателя в этот день нет пар (у ${freeGroupObjects.length > 1 ? 'групп' : 'группы'} ${freeGroupObjects.map((g) => g.label).join(', ')} также нет пар)`;
        } else {
          tooltipText = 'У преподавателя в этот день нет пар';
        }
      } else if (groupFreeDay) {
        badgeLabel = groups.length > 1 ? 'Без пар у групп' : 'Без пар у группы';
        tooltipText = `У ${groups.length > 1 ? 'всех групп' : 'группы'} (${freeGroupObjects.map((g) => g.label).join(', ')}) в этот день нет пар`;
      } else if (freeGroupObjects.length > 0) {
        tooltipText = `У ${freeGroupObjects.length > 1 ? 'групп' : 'группы'} (${freeGroupObjects.map((g) => g.label).join(', ')}) в этот день нет пар`;
      }

      return {
        date,
        dayIndex,
        outOfRange: false,
        teacherFreeDay,
        groupFreeDay,
        bothFreeDay,
        freeDayStatus,
        badgeLabel,
        tooltipText
      };
    });

    weeks.push({
      monday: dates[0], saturday: dates[5], dates, daysStatus,
      rows: SLOTS.map((slot) => ({
        slot,
        cells: dates.map((date) => {
          const outOfRange = date < start || date > finish;
          const selectedSlotsOnDate = SLOTS.filter((s) => selectedKeys?.has(`${date}-${s.number}`)).map((s) => s.number);

          const teacherDailyEvents = teacher.byDate.get(date) ?? [];
          const matchedLessons = outOfRange ? [] : slotEvents(teacherDailyEvents, slot);
          const teacherBusy = matchedLessons.length > 0;
          const lessonDetails = matchedLessons.map(extractLessonDetail);
          const lessons = [...new Set(lessonDetails.map((l) => l.label))];
          const teacherBusySlots = SLOTS.filter((s) => isBusy(teacherDailyEvents, s)).map((s) => s.number);
          const teacherBusyWithSelected = [...new Set([...teacherBusySlots, ...selectedSlotsOnDate])];
          const teacherHasWindow = hasWindowBefore(teacherBusyWithSelected.filter((s) => s !== slot.number), slot.number);

          const groupStatus: GroupSlotDetail[] = groups.map((group) => {
            const dailyEvents = indexedGroups.get(group.id)?.byDate.get(date) ?? [];
            const busy = isBusy(dailyEvents, slot);
            const busySlots = SLOTS.filter((s) => isBusy(dailyEvents, s)).map((s) => s.number);
            const groupBusyWithSelected = [...new Set([...busySlots, ...selectedSlotsOnDate.filter((sNum) => !isBusy(dailyEvents, SLOTS[sNum - 1]))])];
            const hasWindow = hasWindowBefore(groupBusyWithSelected.filter((s) => s !== slot.number), slot.number);
            const groupSlotLessons = slotEvents(dailyEvents, slot);
            const groupLessonDetails = groupSlotLessons.map(extractLessonDetail);
            const lessons = [...new Set(groupLessonDetails.map((l) => l.label))];
            return { group, busy, hasWindow, lessons, lessonDetails: groupLessonDetails };
          });
          const freeGroups = outOfRange ? [] : groupStatus.filter((g) => !g.busy).map((g) => g.group);
          const busyGroups = outOfRange ? [] : groupStatus.filter((g) => g.busy).map((g) => g.group);
          const freeGroupsWithWindow = groupStatus.filter((g) => !g.busy && g.hasWindow).map((g) => g.group.label);
          const groupHasWindow = freeGroupsWithWindow.length > 0;

          const teachersDetails: TeacherSlotDetail[] = outOfRange ? [] : (commissionOptions?.people.map((person) => {
            const dailyEvents = indexedCommission.get(person.id)?.byDate.get(date) ?? [];
            const busy = isBusy(dailyEvents, slot);
            const busySlots = SLOTS.filter((s) => isBusy(dailyEvents, s)).map((s) => s.number);
            const personBusyWithSelected = [...new Set([...busySlots, ...selectedSlotsOnDate.filter((sNum) => !isBusy(dailyEvents, SLOTS[sNum - 1]))])];
            const hasWindow = hasWindowBefore(personBusyWithSelected.filter((s) => s !== slot.number), slot.number);
            const personSlotLessons = slotEvents(dailyEvents, slot);
            const personLessonDetails = personSlotLessons.map(extractLessonDetail);
            const lessons = [...new Set(personLessonDetails.map((l) => l.label))];
            const reason = commissionOptions.failedIds.has(person.id) ? 'load-error' : commissionOptions.mercy && dailyEvents.length === 0 ? 'no-lessons' : busy ? 'busy' : 'free';
            return { person, busy, hasWindow, available: reason === 'free', reason, lessons, lessonDetails: personLessonDetails };
          }) ?? []);
          const commission: CommissionAvailability[] = teachersDetails.map((t) => ({ person: t.person, available: t.available, reason: t.reason }));

          const auditoriumsDetails: AuditoriumSlotDetail[] = (auditoriums ?? []).map((aud) => {
            const dailyEvents = indexedAuditoriums.get(aud.id)?.byDate.get(date) ?? [];
            const busy = isBusy(dailyEvents, slot);
            const audSlotLessons = slotEvents(dailyEvents, slot);
            const audLessonDetails = audSlotLessons.map(extractLessonDetail);
            const lessons = [...new Set(audLessonDetails.map((l) => l.label))];
            return { auditorium: aud, busy, lessons, lessonDetails: audLessonDetails };
          });
          const freeAuditoriums = auditoriumsDetails.filter((a) => !a.busy).map((a) => a.auditorium);
          const busyAuditoriums = auditoriumsDetails.filter((a) => a.busy).map((a) => a.auditorium);
          const auditoriumBusy = (auditoriums?.length ?? 0) > 0 && busyAuditoriums.length > 0;

          const baseAvailable = !outOfRange && (mode === 'meeting' ? commission.length > 0 && commission.every((entry) => entry.available) : mode === 'substitution' ? teacherBusy : !teacherBusy && freeGroups.length > 0);
          const available = baseAvailable && !auditoriumBusy;

          let unavailableReason: UnavailableReason | undefined;
          let unavailableText: string | undefined;

          if (outOfRange) {
            unavailableReason = 'out-of-range';
            unavailableText = 'Вне периода';
          } else if (!available) {
            if (baseAvailable && auditoriumBusy) {
              unavailableReason = busyAuditoriums.length === 1 ? 'auditorium-busy' : 'auditoriums-busy';
              if (busyAuditoriums.length === 1) {
                unavailableText = `Занята ауд. ${busyAuditoriums[0].label}`;
              } else {
                unavailableText = `Заняты: ${busyAuditoriums.map((a) => a.label).join(', ')}`;
              }
            } else if (mode === 'meeting') {
              unavailableReason = 'teachers-busy';
              const busyPersons = commission.filter((entry) => !entry.available).map((entry) => entry.person.label);
              if (commission.length > 0 && busyPersons.length === commission.length) {
                unavailableText = 'Заняты все преподаватели';
              } else if (busyPersons.length === 1) {
                unavailableText = `Пара у ${busyPersons[0]}`;
              } else if (busyPersons.length > 1) {
                unavailableText = `Пара у: ${busyPersons.join(', ')}`;
              } else {
                unavailableText = 'Занято';
              }
            } else if (mode === 'substitution') {
              unavailableReason = 'no-lesson';
              unavailableText = 'Нет занятия';
            } else {
              if (teacherBusy && freeGroups.length === 0) {
                unavailableReason = 'both-busy';
                unavailableText = groups.length > 1 ? 'Пара у преподавателя и у групп' : 'Пара у преподавателя и у группы';
              } else if (teacherBusy) {
                unavailableReason = 'teacher-busy';
                unavailableText = 'Пара у преподавателя';
              } else if (freeGroups.length === 0) {
                unavailableReason = 'group-busy';
                unavailableText = groups.length > 1 ? 'Пара у всех групп' : 'Пара у группы';
              } else {
                unavailableText = 'Занято';
              }
            }
          }

          let windowStatus: WindowStatus = 'none';
          if (available) {
            if (mode === 'meeting') {
              const teachersWithWindow = teachersDetails.filter((t) => t.hasWindow);
              if (teachersWithWindow.length === 0) {
                windowStatus = 'none';
              } else if (teachersWithWindow.length === teachersDetails.length && teachersDetails.length > 1) {
                windowStatus = 'both-window';
              } else {
                windowStatus = 'teacher-window';
              }
            } else {
              if (!teacherHasWindow && !groupHasWindow) {
                windowStatus = 'none';
              } else if (!teacherHasWindow && groupHasWindow) {
                windowStatus = 'group-window';
              } else if (teacherHasWindow && !groupHasWindow) {
                windowStatus = 'teacher-window';
              } else {
                windowStatus = 'both-window';
              }
            }
          }

          return { key: `${date}-${slot.number}`, date, available, teacherBusy, teacherHasWindow, freeGroups, busyGroups, groupsDetails: groupStatus, teachersDetails, freeGroupsWithWindow, lessons, lessonDetails, auditoriumsDetails, freeAuditoriums, busyAuditoriums, auditoriumBusy, outOfRange, commission, windowStatus, unavailableReason, unavailableText };
        })
      }))
    });
  }
  return { weeks, unknownDates };
}

/* ==========================================================================
   Multi-Entity Schedule Viewer
   ========================================================================== */

export type ScheduleViewerEntity = {
  id: string;
  label: string;
  type: 'group' | 'person' | 'auditorium';
};

export type ViewerLessonDetail = {
  discipline: string;
  kindOfWork?: string;
  auditorium?: string;
  building?: string;
  lecturer?: string;
  group?: string;
  subgroup?: string;
  timeStart?: string;
  timeEnd?: string;
  rawEvent: ApiItem;
};

export type ViewerCellLane = {
  entity: ScheduleViewerEntity;
  lessons: ViewerLessonDetail[];
  isFree: boolean;
};

export type ViewerCell = {
  key: string;
  date: string;
  outOfRange: boolean;
  lanes: ViewerCellLane[];
};

export type ViewerRow = {
  slot: Slot;
  cells: ViewerCell[];
};

export type ViewerWeek = {
  monday: string;
  saturday: string;
  dates: string[];
  rows: ViewerRow[];
};

export function buildViewerWeeks(
  start: string,
  finish: string,
  entities: ScheduleViewerEntity[],
  entityEventsMap: Map<string, ApiItem[]>
): ViewerWeek[] {
  const indexed = new Map(entities.map((e) => [e.id, indexEvents(entityEventsMap.get(e.id) ?? [])]));
  const startDate = fromIso(start);
  const monday = addDays(startDate, -((startDate.getDay() + 6) % 7));
  const weeks: ViewerWeek[] = [];

  for (let weekStart = monday; toIso(weekStart) <= finish; weekStart = addDays(weekStart, 7)) {
    const dates = Array.from({ length: 6 }, (_, i) => toIso(addDays(weekStart, i)));
    weeks.push({
      monday: dates[0],
      saturday: dates[5],
      dates,
      rows: SLOTS.map((slot) => ({
        slot,
        cells: dates.map((date) => {
          const outOfRange = date < start || date > finish;
          const lanes: ViewerCellLane[] = entities.map((entity) => {
            const dailyEvents = indexed.get(entity.id)?.byDate.get(date) ?? [];
            const matched = outOfRange ? [] : slotEvents(dailyEvents, slot);
            const lessons: ViewerLessonDetail[] = matched.map((event) => {
              const discipline = extractDiscipline(event);
              const auditorium = extractAuditorium(event);
              const lecturer = extractLecturer(event);
              const group = extractGroup(event);
              const kindOfWork = event.kindOfWork ? String(event.kindOfWork).trim() : undefined;
              const building = event.building ? String(event.building).trim() : undefined;
              const subgroup = (event.subGroup || event.subgroup) ? String(event.subGroup || event.subgroup).trim() : undefined;
              const timeStart = event.beginLesson ? String(event.beginLesson).trim() : slot.start;
              const timeEnd = event.endLesson ? String(event.endLesson).trim() : slot.end;
              return {
                discipline,
                kindOfWork,
                auditorium,
                building,
                lecturer: lecturer ? formatShortName(lecturer) : undefined,
                group,
                subgroup,
                timeStart,
                timeEnd,
                rawEvent: event
              };
            });
            return {
              entity,
              lessons,
              isFree: lessons.length === 0
            };
          });

          return {
            key: `${date}-${slot.number}`,
            date,
            outOfRange,
            lanes
          };
        })
      }))
    });
  }

  return weeks;
}
