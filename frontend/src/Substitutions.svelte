<script lang="ts">
  import AppIcon from './AppIcon.svelte';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { account } from './lib/account';
  import CustomSelect from './CustomSelect.svelte';
  import SearchField from './SearchField.svelte';
  import PlannerPageFrame from './PlannerPageFrame.svelte';
  import PlannerFilterBar from './PlannerFilterBar.svelte';
  import PlannerToolbar from './PlannerToolbar.svelte';
  import { COMMISSION_GROUPS } from './lib/commission';
  import {
    SLOTS,
    addDays,
    buildViewerWeeks,
    countWindowPairsIfOccupied,
    formatPairCount,
    formatDate,
    formatShortName,
    getSchedule,
    searchDepartmentTeachers,
    toIso,
    type ApiItem,
    type SearchItem,
    type Slot,
    type ViewerLessonDetail,
    type ViewerWeek
  } from './lib/schedule';

  const PFI_NAME = 'Прикладная математика и фундаментальная информатика';
  type Status = 'busy' | 'free' | 'window' | 'no-lessons' | 'error';
  type TeacherSlot = { teacher: SearchItem; status: Status; lessons: ViewerLessonDetail[]; windowPairs: number };
  type BoardRow = { date: string; slot: Slot; teachers: TeacherSlot[] };
  type SelectedLesson = { teacher: SearchItem; date: string; slot: Slot; lesson: ViewerLessonDetail };
  type SlotReplacementPick = { replacement: SearchItem; date: string; slot: Slot; target: SelectedLesson | null };
  type Candidate = { person: SearchItem; status: Status | 'loading' | 'error'; windowPairs?: number; lessons?: ViewerLessonDetail[] };
  type HoverLesson = { lesson: ViewerLessonDetail; teacher: SearchItem; date: string; slot: Slot; targetRect: DOMRect };
  type ConfirmedReplacement = { key: string; planId: string; substitutionId: string; status: 'selected' | 'confirmed'; originalTeacher: SearchItem; replacement: SearchItem; date: string; slot: Slot; lesson: ViewerLessonDetail; issues?: { kind: string; lesson?: string; start?: string; end?: string }[]; conflictHash?: string; serverMessage?: string };
  type PlanApiError = Error & { status?: number; detail?: unknown };
  let confirmationReasons: Record<string, string> = {};
  let savingReplacement = false;

  function mondayOf(date: Date) {
    const monday = new Date(date);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    return monday;
  }
  const today = new Date();
  let currentDateIso = toIso(today);
  const firstMonday = mondayOf(today);
  let start = toIso(firstMonday);
  let finish = toIso(addDays(firstMonday, 12));
  let department = 'ПМФИ';
  let activeOnly = true;
  let showFreeTeachers = false;
  let showWindowTeachers = false;
  let showSubjects = false;
  let showGroups = false;
  let showAuditoriums = false;
  let hideDepartmentMeetings = false;
  let activeLessonTooltip: HoverLesson | null = null;
  let teachers: SearchItem[] = [];
  let weeks: ViewerWeek[] = [];
  let rows: BoardRow[] = [];
  let eventsByTeacher = new Map<string, ApiItem[]>();
  let failedTeacherIds = new Set<string>();
  let loading = false;
  let error = '';
  let hasLoaded = false;
  let selectedLesson: SelectedLesson | null = null;
  let slotReplacementPick: SlotReplacementPick | null = null;
  let pickedReplacement: SearchItem | null = null;
  let confirmedReplacements: ConfirmedReplacement[] = [];
  let showConfirmedReplacements = false;
  let boardNotice = '';
  let candidateMode: 'department' | 'topic' | 'other' = 'department';
  let topicId = '';
  let selectedOthers: SearchItem[] = [];
  let otherSchedules = new Map<string, ApiItem[]>();
  let otherLoading = false;
  let topicSchedules = new Map<string, ApiItem[]>();
  let topicFailedIds = new Set<string>();
  let otherFailedIds = new Set<string>();
  let topicLoading = false;
  let topicRequestId = 0;
  let notice = '';
  let rowStatusIndex = new Map<string, TeacherSlot>();
  let boardRequestId = 0;
  let refreshTimer: number | null = null;
  $: rowStatusIndex = indexRows(rows);

  function indexRows(items: BoardRow[]): Map<string, TeacherSlot> {
    const index = new Map<string, TeacherSlot>();
    for (const row of items) {
      for (const item of row.teachers) index.set(`${row.date}:${row.slot.number}:${item.teacher.id}`, item);
    }
    return index;
  }

  function normalizedDepartment() {
    return department.trim().toLocaleLowerCase('ru-RU') === 'пмфи' ? PFI_NAME : department.trim();
  }

  function isDepartmentMeeting(lesson: ViewerLessonDetail) {
    const text = `${lesson.discipline} ${lesson.kindOfWork ?? ''}`.toLocaleLowerCase('ru-RU');
    return text.includes('заседан') && text.includes('кафедр');
  }

  function visibleSubstitutionLanes(
    cell: ViewerWeek['rows'][number]['cells'][number],
    date: string,
    slot: number,
    hideMeetings: boolean,
    filterActiveOnly: boolean,
    includeFree: boolean,
    includeWindows: boolean
  ) {
    return cell.lanes.filter((lane) => {
      const state = teacherSlot(date, slot, lane.entity.id);
      if (!state) return false;
      if (filterActiveOnly && state.status !== 'busy' && state.status !== 'error' && !(includeFree && state.status === 'free') && !(includeWindows && state.status === 'window')) return false;
      return !(hideMeetings && state.status === 'busy' && state.lessons.length > 0 && state.lessons.every(isDepartmentMeeting));
    });
  }

  function makeRows(scheduleWeeks: ViewerWeek[], people: SearchItem[], failedIds: Set<string>): BoardRow[] {
    const busyByDay = new Map<string, Set<number>>();
    for (const week of scheduleWeeks) {
      for (const row of week.rows) {
        for (const cell of row.cells) {
          for (const lane of cell.lanes) {
            if (!lane.lessons.length) continue;
            const key = `${lane.entity.id}:${cell.date}`;
            const slots = busyByDay.get(key) ?? new Set<number>();
            slots.add(row.slot.number);
            busyByDay.set(key, slots);
          }
        }
      }
    }
    const built: BoardRow[] = [];
    for (const week of scheduleWeeks) {
      for (const date of week.dates) {
        if (date < start || date > finish) continue;
        for (const slot of SLOTS) {
          const cell = week.rows.find((row) => row.slot.number === slot.number)?.cells.find((item) => item.date === date);
          if (!cell || cell.outOfRange) continue;
          built.push({
            date,
            slot,
            teachers: people.map((person) => {
              const lane = cell.lanes.find((item) => item.entity.id === person.id);
              const lessons = lane?.lessons ?? [];
              const dailySlots = [...(busyByDay.get(`${person.id}:${date}`) ?? [])];
              const windowPairs = !failedIds.has(person.id) && lessons.length === 0 && dailySlots.length
                ? countWindowPairsIfOccupied(dailySlots, slot.number)
                : 0;
              const status: Status = failedIds.has(person.id)
                ? 'error'
                : lessons.length
                ? 'busy'
                : dailySlots.length === 0
                  ? 'no-lessons'
                  : windowPairs > 0 ? 'window' : 'free';
              return { teacher: person, status, lessons, windowPairs };
            })
          });
        }
      }
    }
    return built;
  }

  async function fetchSchedules(people: SearchItem[], from: string, until: string) {
    const map = new Map<string, ApiItem[]>();
    const failed = new Set<string>();
    for (let offset = 0; offset < people.length; offset += 5) {
      const batch = people.slice(offset, offset + 5);
      const result = await Promise.all(batch.map(async (person) => {
        try { return await getSchedule('person', person.id, from, until); }
        catch { failed.add(person.id); return []; }
      }));
      result.forEach((schedule, index) => map.set(batch[index].id, schedule));
    }
    return { events: map, failed };
  }

  async function refreshBoard() {
    if (!start || !finish || start > finish || !department.trim()) return;
    const requestId = ++boardRequestId;
    const requestedStart = start;
    const requestedFinish = finish;
    loading = true;
    error = '';
    notice = '';
    selectedLesson = null;
    try {
      const query = normalizedDepartment();
      const matching = await searchDepartmentTeachers(query);
      if (requestId !== boardRequestId) return;
      if (!matching.length) {
        teachers = [];
        rows = [];
        weeks = [];
        eventsByTeacher = new Map();
        failedTeacherIds = new Set();
        hasLoaded = true;
        error = `По запросу «${department}» преподаватели не найдены. Уточните название кафедры.`;
        return;
      }
      teachers = matching;
      const loaded = await fetchSchedules(matching, requestedStart, requestedFinish);
      if (requestId !== boardRequestId) return;
      eventsByTeacher = loaded.events;
      failedTeacherIds = loaded.failed;
      const entities = matching.map((person) => ({ id: person.id, label: person.label, type: 'person' as const }));
      weeks = buildViewerWeeks(start, finish, entities, eventsByTeacher);
      rows = makeRows(weeks, matching, failedTeacherIds);
      hasLoaded = true;
    } catch (cause) {
      if (requestId === boardRequestId) error = cause instanceof Error ? cause.message : 'Не удалось загрузить расписания преподавателей.';
    } finally {
      if (requestId === boardRequestId) loading = false;
    }
  }

  function queueRefresh() {
    boardRequestId++;
    if (refreshTimer !== null) window.clearTimeout(refreshTimer);
    selectedLesson = null;
    slotReplacementPick = null;
    pickedReplacement = null;
    loading = false;
    hasLoaded = false;
    rows = [];
    weeks = [];
    eventsByTeacher = new Map();
    failedTeacherIds = new Set();
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null;
      void refreshBoard();
    }, 250);
  }

  function lessonTitle(lesson: ViewerLessonDetail) {
    return [lesson.discipline, lesson.kindOfWork, lesson.group, lesson.auditorium ? `ауд. ${lesson.auditorium}` : ''].filter(Boolean).join(' · ');
  }

  function teacherSlot(date: string, slotNumber: number, id: string): TeacherSlot | undefined {
    return rowStatusIndex.get(`${date}:${slotNumber}:${id}`);
  }

  function showLessonTooltip(event: MouseEvent | FocusEvent, lesson: ViewerLessonDetail, teacher: SearchItem, date: string, slot: Slot) {
    const target = event.currentTarget as HTMLElement | null;
    if (target) activeLessonTooltip = { lesson, teacher, date, slot, targetRect: target.getBoundingClientRect() };
  }

  function positionSubTooltip(node: HTMLElement, targetRect: DOMRect) {
    function position(rect: DOMRect) {
      const margin = 12;
      const gap = 8;
      const width = node.offsetWidth;
      const height = node.offsetHeight;
      const left = Math.max(margin, Math.min(window.innerWidth - width - margin, rect.left + rect.width / 2 - width / 2));
      const top = rect.top - height - gap >= margin ? rect.top - height - gap : Math.min(window.innerHeight - height - margin, rect.bottom + gap);
      node.style.left = `${Math.round(left)}px`;
      node.style.top = `${Math.round(Math.max(margin, top))}px`;
      node.classList.toggle('tooltip-top', top < rect.top);
      node.classList.toggle('tooltip-bottom', top >= rect.top);
    }
    position(targetRect);
    const resize = () => position(targetRect);
    window.addEventListener('resize', resize);
    return { update(rect: DOMRect) { targetRect = rect; position(targetRect); }, destroy() { window.removeEventListener('resize', resize); } };
  }

  function openReplacement(teacher: SearchItem, date: string, slot: Slot, lesson: ViewerLessonDetail) {
    slotReplacementPick = null;
    topicRequestId++;
    topicLoading = false;
    activeLessonTooltip = null;
    selectedLesson = { teacher, date, slot, lesson };
    pickedReplacement = null;
    candidateMode = 'department';
    topicId = '';
    selectedOthers = [];
    topicSchedules = new Map();
    otherSchedules = new Map();
    notice = '';
  }

  function openSlotReplacementPick(replacement: SearchItem, date: string, slot: Slot) {
    const row = rows.find((item) => item.date === date && item.slot.number === slot.number);
    const hasTargets = row?.teachers.some((item) => item.status === 'busy' && item.teacher.id !== replacement.id && item.lessons.length) ?? false;
    if (!hasTargets) {
      boardNotice = `На ${slot.number}-й паре ${formatDate(date)} нет занятий, которым нужна замена.`;
      return;
    }
    activeLessonTooltip = null;
    selectedLesson = null;
    pickedReplacement = null;
    slotReplacementPick = { replacement, date, slot, target: null };
    notice = '';
  }

  function slotReplacementTargets(pick: SlotReplacementPick): SelectedLesson[] {
    const row = rows.find((item) => item.date === pick.date && item.slot.number === pick.slot.number);
    const targets: SelectedLesson[] = [];
    for (const item of row?.teachers ?? []) {
      if (item.status !== 'busy' || item.teacher.id === pick.replacement.id) continue;
      for (const lesson of item.lessons) targets.push({ teacher: item.teacher, date: pick.date, slot: pick.slot, lesson });
    }
    return targets;
  }

  function openClickedLesson(event: Event, teacher: SearchItem, date: string, slot: Slot, lessons: ViewerLessonDetail[]) {
    const target = event.target as HTMLElement;
    const lessonIndex = Number(target.closest('[data-lesson-index]')?.getAttribute('data-lesson-index') ?? 0);
    const lesson = lessons[lessonIndex] ?? lessons[0];
    if (lesson) openReplacement(teacher, date, slot, lesson);
  }

  function statusFor(events: Map<string, ApiItem[]>, person: SearchItem, date: string, slotNumber: number): { status: Status; windowPairs: number; lessons: ViewerLessonDetail[] } {
    if (!events.has(person.id)) return { status: 'error', windowPairs: 0, lessons: [] };
    const personWeeks = buildViewerWeeks(start, finish, [{ id: person.id, label: person.label, type: 'person' }], events);
    const busySlots: number[] = [];
    let busyLessons: ViewerLessonDetail[] = [];
    for (const week of personWeeks) {
      for (const row of week.rows) {
        const cell = row.cells.find((item) => item.date === date);
        const lane = cell?.lanes[0];
        if (lane?.lessons.length) busySlots.push(row.slot.number);
        if (row.slot.number === slotNumber && lane?.lessons.length) busyLessons = lane.lessons;
      }
    }
    if (busyLessons.length) return { status: 'busy', windowPairs: 0, lessons: busyLessons };
    if (!busySlots.length) return { status: 'no-lessons', windowPairs: 0, lessons: [] };
    const windowPairs = countWindowPairsIfOccupied(busySlots, slotNumber);
    return { status: windowPairs ? 'window' : 'free', windowPairs, lessons: [] };
  }

  $: selectedTopic = COMMISSION_GROUPS.find((group) => group.id === topicId);
  $: topicPeople = selectedTopic?.people.filter((person) => person.id !== selectedLesson?.teacher.id) ?? [];
  function getDepartmentCandidates(selection: SelectedLesson | null): Candidate[] {
    if (!selection) return [];
    const row = rows.find((item) => item.date === selection.date && item.slot.number === selection.slot.number);
    return sortCandidates(row?.teachers.filter((item) => item.teacher.id !== selection.teacher.id).map((item) => ({ person: item.teacher, status: item.status, windowPairs: item.windowPairs, lessons: item.lessons })) ?? []);
  }

  function sortCandidates(items: Candidate[]): Candidate[] {
    const priority: Record<Candidate['status'], number> = { free: 0, window: 1, 'no-lessons': 2, busy: 3, error: 4, loading: 5 };
    return [...items].sort((a, b) => priority[a.status] - priority[b.status]);
  }
  $: departmentCandidates = getDepartmentCandidates(selectedLesson);
  $: topicCandidates = selectedLesson ? sortCandidates(topicPeople.map((person) => {
    const availability = topicFailedIds.has(person.id)
      ? { status: 'error' as const, windowPairs: 0 }
      : topicSchedules.has(person.id)
        ? statusFor(topicSchedules, person, selectedLesson!.date, selectedLesson!.slot.number)
        : { status: topicLoading ? 'loading' as const : 'error' as const, windowPairs: 0 };
    return { person, ...availability };
  })) : [];
  $: otherCandidates = selectedLesson ? sortCandidates(selectedOthers.map((person) => {
    const availability = otherFailedIds.has(person.id)
      ? { status: 'error' as const, windowPairs: 0 }
      : otherSchedules.has(person.id)
        ? statusFor(otherSchedules, person, selectedLesson!.date, selectedLesson!.slot.number)
        : { status: otherLoading ? 'loading' as const : 'error' as const, windowPairs: 0 };
    return { person, ...availability };
  })) : [];

  async function chooseTopic(id: string) {
    const requestId = ++topicRequestId;
    topicId = id;
    topicLoading = false;
    topicSchedules = new Map();
    topicFailedIds = new Set();
    if (!id || !selectedLesson) return;
    const people = COMMISSION_GROUPS.find((group) => group.id === id)?.people.filter((person) => person.id !== selectedLesson?.teacher.id) ?? [];
    const departmentIds = new Set(teachers.map((person) => person.id));
    const cachedSchedules = new Map<string, ApiItem[]>();
    const cachedFailures = new Set<string>();
    for (const person of people) {
      if (!departmentIds.has(person.id)) continue;
      const schedule = eventsByTeacher.get(person.id);
      if (schedule) cachedSchedules.set(person.id, schedule);
      if (failedTeacherIds.has(person.id)) cachedFailures.add(person.id);
    }
    topicSchedules = cachedSchedules;
    topicFailedIds = cachedFailures;

    const remainingPeople = people.filter((person) => !departmentIds.has(person.id));
    if (!remainingPeople.length) return;
    topicLoading = true;
    try {
      const loaded = await fetchSchedules(remainingPeople, start, finish);
      if (requestId !== topicRequestId) return;
      topicSchedules = new Map([...cachedSchedules, ...loaded.events]);
      topicFailedIds = new Set([...cachedFailures, ...loaded.failed]);
    } finally {
      if (requestId === topicRequestId) topicLoading = false;
    }
  }

  async function addOther(person: SearchItem) {
    if (!selectedLesson || person.id === selectedLesson.teacher.id || selectedOthers.some((item) => item.id === person.id)) return;
    selectedOthers = [...selectedOthers, person];
    otherFailedIds.delete(person.id);
    otherFailedIds = new Set(otherFailedIds);
    otherLoading = true;
    try {
      const schedule = await getSchedule('person', person.id, start, finish);
      otherSchedules = new Map(otherSchedules).set(person.id, schedule);
    } catch {
      otherFailedIds = new Set(otherFailedIds).add(person.id);
      notice = `Не удалось загрузить расписание ${person.label}.`;
    } finally { otherLoading = false; }
  }

  function removeOther(id: string) {
    selectedOthers = selectedOthers.filter((person) => person.id !== id);
    const next = new Map(otherSchedules);
    next.delete(id);
    otherSchedules = next;
    otherFailedIds.delete(id);
    otherFailedIds = new Set(otherFailedIds);
  }

  function candidateStatusText(candidate: Candidate) {
    const { status, windowPairs = 0 } = candidate;
    return status === 'error' ? 'нет данных' : status === 'busy' ? 'занят' : status === 'free' ? 'свободен' : status === 'window' ? `Окно (${formatPairCount(windowPairs)})` : status === 'no-lessons' ? 'нет занятий сегодня' : status === 'loading' ? 'загружаем…' : 'ошибка расписания';
  }

  function candidateBusyText(candidate: Candidate) {
    return (candidate.lessons ?? []).map((lesson) => [lesson.discipline, lesson.group, lesson.auditorium ? `ауд. ${lesson.auditorium}` : ''].filter(Boolean).join(' · ')).join('; ');
  }

  function teacherActionLabel(state: TeacherSlot) {
    if (state.status === 'busy') return `${state.teacher.label}: ${lessonTitle(state.lessons[0])}. Нажмите, чтобы подобрать замену.`;
    if (state.status === 'error') return `${state.teacher.label}: расписание не загружено.`;
    return `${state.teacher.label}: ${candidateStatusText({ person: state.teacher, status: state.status, windowPairs: state.windowPairs })}. Нажмите, чтобы выбрать, кого заменить на эту пару.`;
  }

  function slotTargetKey(target: SelectedLesson) {
    const lessonId = String(target.lesson.rawEvent.lessonOid ?? `${target.lesson.discipline}:${target.lesson.group ?? ''}:${target.lesson.subgroup ?? ''}`);
    return `${target.teacher.id}:${lessonId}`;
  }

  function selectReplacement(candidate: Candidate) {
    if (candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons') return;
    pickedReplacement = candidate.person;
    notice = `${candidate.person.label} выбрано. Подтвердите замену кнопкой ниже.`;
  }

  async function plansRequest(path: string, method = 'GET', body?: unknown) {
    const session = get(account);
    if (!session?.token || !session.departmentId) throw new Error('Войдите в аккаунт кафедры, чтобы сохранять замены.');
    const response = await fetch(`/backend-api/plans${path}`, {
      method,
      headers: { Authorization: `Bearer ${session.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    if (!response.ok) {
      let payload: any = {};
      try { payload = await response.json(); } catch { /* The server may return an empty response. */ }
      const err = new Error(typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || `Ошибка API (${response.status})`) as PlanApiError;
      err.status = response.status;
      err.detail = payload.detail;
      throw err;
    }
    return response.status === 204 ? null : response.json();
  }

  async function getSubstitutionPlan() {
    const session = get(account);
    if (!session?.departmentId) throw new Error('Войдите в аккаунт кафедры, чтобы сохранять замены.');
    const plans = await plansRequest(`?department_id=${encodeURIComponent(session.departmentId)}`) as any[];
    let plan = plans.find((item) => item.kind === 'substitution' && item.status === 'draft');
    if (!plan) plan = await plansRequest('', 'POST', { department_id: session.departmentId, kind: 'substitution', title: 'Замены занятий' });
    return plansRequest(`/${plan.id}`) as Promise<any>;
  }

  function replacementFromSnapshot(row: any): ConfirmedReplacement | null {
    const snapshot = row.source_snapshot ?? {};
    const lessonData = snapshot.lesson ?? {};
    const teacherId = String(row.original_person_id ?? '');
    const replacementId = String(row.substitute_person_id ?? '');
    const date = String(row.event_date ?? '').slice(0, 10);
    const startTime = String(row.starts_at ?? '').slice(0, 5);
    const endTime = String(row.ends_at ?? '').slice(0, 5);
    const slotNumber = Number(row.slot_number);
    if (!teacherId || !replacementId || !date || !slotNumber) return null;
    return {
      key: String(snapshot.client_key ?? `${teacherId}:${date}:${slotNumber}:${row.substitution_id}`),
      planId: String(row.plan_id),
      substitutionId: String(row.substitution_id),
      status: row.substitution_status === 'confirmed' ? 'confirmed' : 'selected',
      originalTeacher: { id: teacherId, label: String(snapshot.original_label ?? teacherId), description: String(snapshot.original_description ?? '') },
      replacement: { id: replacementId, label: String(snapshot.replacement_label ?? replacementId), description: String(snapshot.replacement_description ?? '') },
      date,
      slot: { number: slotNumber, start: startTime, end: endTime },
      lesson: { discipline: String(lessonData.discipline ?? 'Занятие'), kindOfWork: lessonData.kindOfWork || undefined, auditorium: lessonData.auditorium || undefined, building: lessonData.building || undefined, group: lessonData.group || undefined, subgroup: lessonData.subgroup || undefined, lecturer: lessonData.lecturer || undefined, rawEvent: lessonData.rawEvent ?? {} }
    };
  }

  async function loadConfirmedReplacements() {
    const session = get(account);
    if (!session?.departmentId || !session?.token) { confirmedReplacements = []; return; }
    try {
      const rows = await plansRequest(`/substitutions?department_id=${encodeURIComponent(session.departmentId)}`) as any[];
      confirmedReplacements = rows.map(replacementFromSnapshot).filter((item): item is ConfirmedReplacement => Boolean(item));
      boardNotice = '';
    } catch (cause) {
      boardNotice = cause instanceof Error ? `Не удалось загрузить общий список замен: ${cause.message}` : 'Не удалось загрузить общий список замен.';
    }
  }

  function substitutionSnapshot(selection: SelectedLesson, replacement: SearchItem, key: string) {
    const lesson = selection.lesson;
    const rawEvent: ApiItem = {};
    for (const field of ['lessonOid','discipline','kindOfWork','group','groupOid','groupId','group_id','subgroup','auditorium','auditoriumOid','building','lecturer','date','beginLesson','endLesson']) {
      if (lesson.rawEvent[field] != null) rawEvent[field] = lesson.rawEvent[field];
    }
    return {
      client_key: key,
      original_label: selection.teacher.label,
      original_description: selection.teacher.description,
      replacement_label: replacement.label,
      replacement_description: replacement.description,
      lesson: {
        discipline: lesson.discipline, kindOfWork: lesson.kindOfWork ?? null,
        auditorium: lesson.auditorium ?? null, building: lesson.building ?? null,
        lecturer: lesson.lecturer ?? null, group: lesson.group ?? null, subgroup: lesson.subgroup ?? null,
        rawEvent
      }
    };
  }

  async function confirmStoredReplacement(item: ConfirmedReplacement, reason = '', retry = true) {
    try {
      const detail = await plansRequest(`/${item.planId}`) as any;
      await plansRequest(`/${item.planId}/substitutions/${item.substitutionId}/confirm`, 'POST', { version: detail.version, ...(reason.trim() ? { reason: reason.trim(), expected_conflict_hash: item.conflictHash } : {}) });
      const updated = { ...item, status: 'confirmed' as const, issues: undefined, conflictHash: undefined, serverMessage: undefined };
      confirmedReplacements = confirmedReplacements.map((entry) => entry.key === item.key ? updated : entry);
      confirmationReasons = { ...confirmationReasons, [item.key]: '' };
      boardNotice = '';
      return true;
    } catch (cause) {
      const err = cause as PlanApiError;
      const detail = err.detail as any;
      if (err.status === 409 && detail?.conflict_hash) {
        const updated = { ...item, status: 'selected' as const, issues: detail.issues ?? [], conflictHash: detail.conflict_hash, serverMessage: detail.message };
        confirmedReplacements = confirmedReplacements.map((entry) => entry.key === item.key ? updated : entry);
        boardNotice = 'Сервер обнаружил обстоятельства, требующие подтверждения причины.';
        return false;
      }
      if (err.status === 409 && retry && err.message.includes('План изменился')) return confirmStoredReplacement(item, reason, false);
      const updated = { ...item, status: 'selected' as const, serverMessage: typeof detail === 'object' ? detail?.message : err.message };
      confirmedReplacements = confirmedReplacements.map((entry) => entry.key === item.key ? updated : entry);
      boardNotice = `Замена сохранена, но сервер пока не подтвердил её: ${updated.serverMessage ?? err.message}`;
      return false;
    }
  }

  async function saveReplacement(selection: SelectedLesson, replacement: SearchItem) {
    if (savingReplacement) return;
    savingReplacement = true;
    boardNotice = '';
    const lessonId = String(selection.lesson.rawEvent.lessonOid ?? `${selection.lesson.discipline}:${selection.lesson.group ?? ''}:${selection.lesson.subgroup ?? ''}`);
    const key = `${selection.teacher.id}:${selection.date}:${selection.slot.number}:${lessonId}`;
    try {
      if (!/^\d{1,20}$/.test(selection.teacher.id) || !/^\d{1,20}$/.test(replacement.id)) throw new Error('Не удалось определить ID преподавателя в расписании.');
      let plan: any;
      let slot: any;
      let substitution: any;
      for (let attempt = 0; attempt < 2; attempt++) {
        plan = await getSubstitutionPlan();
        const existing = (plan.slots ?? []).flatMap((entry: any) => (entry.substitutions ?? []).map((sub: any) => ({ ...sub, event_date: entry.event_date, slot_number: entry.slot_number, starts_at: entry.starts_at, ends_at: entry.ends_at, slot_id: entry.id, plan_id: plan.id }))).find((sub: any) => sub.source_snapshot?.client_key === key && sub.status !== 'cancelled');
        if (existing) {
          if (String(existing.substitute_person_id) !== replacement.id) throw new Error('Для этого занятия уже сохранена другая замена. Отмените её в списке, затем выберите нового преподавателя.');
          await loadConfirmedReplacements();
          return;
        }
        slot = (plan.slots ?? []).find((entry: any) => String(entry.event_date).slice(0, 10) === selection.date && Number(entry.slot_number) === selection.slot.number);
        if (!slot) {
          try {
            const result = await plansRequest(`/${plan.id}/slots`, 'POST', { version: plan.version, event_date: selection.date, slot_number: selection.slot.number, starts_at: `${selection.slot.start}:00`, ends_at: `${selection.slot.end}:00`, resources: [{ kind: 'person', external_id: selection.teacher.id, display_name: selection.teacher.label }] });
            slot = { id: result.id };
            plan.version = result.version;
          } catch (cause) {
            if ((cause as PlanApiError).status === 409 && attempt === 0) continue;
            throw cause;
          }
        }
        try {
          substitution = await plansRequest(`/${plan.id}/substitutions`, 'POST', { version: plan.version, slot_id: slot.id, original_person_id: selection.teacher.id, substitute_person_id: replacement.id, source_snapshot: substitutionSnapshot(selection, replacement, key) });
          break;
        } catch (cause) {
          if ((cause as PlanApiError).status === 409 && attempt === 0) continue;
          throw cause;
        }
      }
      if (!substitution?.id || !plan?.id) throw new Error('Не удалось сохранить замену. Обновите страницу и попробуйте снова.');
      const entry: ConfirmedReplacement = { key, planId: plan.id, substitutionId: substitution.id, status: 'selected', originalTeacher: selection.teacher, replacement, date: selection.date, slot: selection.slot, lesson: selection.lesson };
      confirmedReplacements = [...confirmedReplacements.filter((item) => item.key !== key), entry];
      await confirmStoredReplacement(entry);
    } catch (cause) {
      boardNotice = cause instanceof Error ? cause.message : 'Не удалось сохранить замену.';
    } finally { savingReplacement = false; }
  }

  async function saveConfirmedReplacement() {
    if (!selectedLesson || !pickedReplacement) return;
    const selection = selectedLesson;
    const replacement = pickedReplacement;
    await saveReplacement(selection, replacement);
    if (!boardNotice || confirmedReplacements.some((item) => item.date === selection.date && item.slot.number === selection.slot.number && item.originalTeacher.id === selection.teacher.id && item.replacement.id === replacement.id)) {
      selectedLesson = null;
      pickedReplacement = null;
    }
  }

  async function confirmSlotReplacement() {
    if (!slotReplacementPick?.target) return;
    const selection = slotReplacementPick.target;
    await saveReplacement(selection, slotReplacementPick.replacement);
    if (confirmedReplacements.some((item) => item.date === selection.date && item.slot.number === selection.slot.number && item.originalTeacher.id === selection.teacher.id && item.replacement.id === slotReplacementPick?.replacement.id)) slotReplacementPick = null;
  }

  async function confirmPendingReplacement(item: ConfirmedReplacement) {
    if (await confirmStoredReplacement(item, confirmationReasons[item.key] ?? '')) await loadConfirmedReplacements();
  }

  async function removeConfirmedReplacement(key: string) {
    const item = confirmedReplacements.find((entry) => entry.key === key);
    if (!item) return;
    try {
      const plan = await plansRequest(`/${item.planId}`) as any;
      await plansRequest(`/${item.planId}/substitutions/${item.substitutionId}/cancel`, 'POST', { version: plan.version });
      await loadConfirmedReplacements();
      boardNotice = '';
    } catch (cause) { boardNotice = cause instanceof Error ? `Не удалось отменить замену: ${cause.message}` : 'Не удалось отменить замену.'; }
  }

  async function openConfirmedReplacements() {
    await loadConfirmedReplacements();
    showConfirmedReplacements = true;
  }

  onMount(() => {
    const updateCurrentDate = () => { currentDateIso = toIso(new Date()); };
    const currentDateTimer = window.setInterval(updateCurrentDate, 60_000);
    void loadConfirmedReplacements();
    void refreshBoard();
    return () => { window.clearInterval(currentDateTimer); if (refreshTimer !== null) window.clearTimeout(refreshTimer); boardRequestId++; };
  });
</script>

<PlannerPageFrame section="ПЛАНИРОВАНИЕ" sectionNumber="03" breadcrumb="Замены" title="Замены занятий" description="Найдите занятие на кафедре и подберите свободного коллегу для замены" icon="⇄" on:home>
  <button class="selection-bar confirmed-replacements-trigger" type="button" aria-label={`Открыть выбранные замены: ${confirmedReplacements.length}`} on:click={openConfirmedReplacements}>
    <span class="selection-count" aria-hidden="true">{confirmedReplacements.length}</span>
    <span><strong>Выбранные замены</strong><small>Посмотреть список</small></span>
    <span class="confirmed-replacements-open"><AppIcon name="arrow-up-right" size={18} /></span>
  </button>
  <PlannerFilterBar slot="filters" ariaLabel="Фильтры расписания замен">
    <div class="sub-filter department-filter"><span class="sub-filter-label">Кафедра</span><span class="department-value">ПМФИ</span></div>
    <div class="sub-filter"><label for="sub-start">Период с</label><input id="sub-start" type="date" bind:value={start} on:change={queueRefresh} /></div>
    <div class="sub-filter"><label for="sub-finish">по</label><input id="sub-finish" type="date" min={start} bind:value={finish} on:change={queueRefresh} /></div>
  </PlannerFilterBar>

  <PlannerToolbar slot="toolbar" ariaLabel="Обозначения и настройки расписания">
    <div slot="legend" class="planner-toolbar-legend substitution-legend">
      <span><i class="sub-legend-dot free"></i>Свободен без окон</span>
      <span><i class="sub-legend-dot window"></i>Свободен, есть окна</span>
      <span><i class="sub-legend-dot no-lessons"></i>Нет занятий сегодня</span>
      <span><i class="sub-legend-dot busy"></i>Занятие</span>
      <p class="substitution-help"><strong>Как подобрать:</strong> нажмите занятие, чтобы выбрать заменяющего. Нажмите строку без занятия, чтобы назначить преподавателя на эту пару и выбрать, кого заменить.</p>
    </div>
    <div slot="options" class="planner-toolbar-options sub-display-options" aria-label="Настройки отображения расписания">
      <div class="sub-status-options" aria-label="Фильтры занятости">
        <label class="sub-display-option" class:active={activeOnly} title="Скрывает преподавателей без занятий в течение дня"><input type="checkbox" bind:checked={activeOnly} /> Скрывать без пар сегодня</label>
        <label class="sub-display-option" class:active={showFreeTeachers} title="Показывает преподавателей, свободных в выбранную пару и без окон в течение дня"><input type="checkbox" bind:checked={showFreeTeachers} /> Свободные без окон</label>
        <label class="sub-display-option" class:active={showWindowTeachers} title="Показывает преподавателей, свободных в выбранную пару, но с окнами в течение дня"><input type="checkbox" bind:checked={showWindowTeachers} /> Свободные с окнами</label>
      </div>
      <div class="sub-detail-options" aria-label="Отображаемые сведения">
        <label class="sub-display-option" class:active={hideDepartmentMeetings} title="Скрывает преподавателей, у которых в этой паре заседание кафедры"><input type="checkbox" bind:checked={hideDepartmentMeetings} /> Скрывать заседания кафедр</label>
        <label class="sub-display-option" class:active={showSubjects} title="Отображать названия занятий"><input type="checkbox" bind:checked={showSubjects} /> Предметы</label>
        <label class="sub-display-option" class:active={showGroups} title="Отображать группы занятий"><input type="checkbox" bind:checked={showGroups} /> Группы</label>
        <label class="sub-display-option" class:active={showAuditoriums} title="Отображать аудитории занятий"><input type="checkbox" bind:checked={showAuditoriums} /> Аудитории</label>
      </div>
    </div>
  </PlannerToolbar>
  {#if boardNotice}<p class="sub-board-notice" role="status">{boardNotice}</p>{/if}
  {#if failedTeacherIds.size}
    <p class="warning-note">Не удалось загрузить расписание {failedTeacherIds.size} преподавателей. Их строки оставлены в таблице с отметкой «Нет данных».</p>
  {/if}

  {#if error}<div class="sub-state error">{error}</div>
  {:else if loading && !hasLoaded}<div class="sub-state">Загружаю преподавателей кафедры и их расписания…</div>
  {:else if hasLoaded && !teachers.length}<div class="sub-state">По этому фильтру преподавателей не найдено.</div>
  {:else if hasLoaded}
    {#each weeks as week (week.monday)}
      <section class="week-block sub-week">
        <div class="week-title"><div><span>НЕДЕЛЯ</span><h3>{formatDate(week.monday)} — {formatDate(week.saturday)}</h3></div><span>ПН — СБ · {teachers.length} НА КАФЕДРЕ</span></div>
        <div class="table-scroll">
          <div class="schedule-table viewer-schedule-table sub-schedule-table" role="table" aria-label={`Неделя ${formatDate(week.monday)} — ${formatDate(week.saturday)}`}>
            <div class="table-row table-head" role="row">
              <div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>
              {#each week.dates as date, day}<div role="columnheader" class:today-column={date === currentDateIso}><div class="head-day-info"><strong>{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'][day]}</strong><span>{formatDate(date, { day: '2-digit', month: '2-digit' })}</span></div></div>{/each}
            </div>
            {#each week.rows as row (row.slot.number)}
              <div class="table-row" role="row">
                <div class="slot-label" role="rowheader"><strong>{String(row.slot.number).padStart(2, '0')}</strong><span>{row.slot.start}<br />{row.slot.end}</span></div>
                {#each row.cells as cell (cell.key)}
                  {@const visibleLanes = visibleSubstitutionLanes(cell, cell.date, row.slot.number, hideDepartmentMeetings, activeOnly, showFreeTeachers, showWindowTeachers)}
                  <div role="cell" class="cell-wrap viewer-cell-wrap sub-schedule-cell" class:today-column={cell.date === currentDateIso} class:out-of-range={cell.outOfRange} class:sub-cell-empty={visibleLanes.length === 0}>
                    {#if cell.outOfRange}
                      <div class="slot-cell out-of-range"><span class="cell-muted">Вне периода</span></div>
                    {:else}
                      <div class="viewer-lines-stack" class:sub-empty-lines={visibleLanes.length === 0}>
                        {#each visibleLanes as lane (lane.entity.id)}
                          {@const state = teacherSlot(cell.date, row.slot.number, lane.entity.id)}
                          {#if state}
                            <div class="viewer-entity-line sub-teacher-line" class:details-lines={showSubjects || showGroups || showAuditoriums} role="button" aria-disabled={state.status === 'error'} tabindex={state.status === 'error' ? -1 : 0} aria-label={teacherActionLabel(state)} title={state.status === 'error' ? 'Расписание не загружено' : 'Нажмите, чтобы подобрать замену'} class:line-busy={state.status === 'busy'} class:sub-free={state.status === 'free'} class:sub-window={state.status === 'window'} class:sub-no-lessons={state.status === 'no-lessons'} class:sub-error={state.status === 'error'} on:mouseenter={(event) => state.lessons[0] && showLessonTooltip(event, state.lessons[0], state.teacher, cell.date, row.slot)} on:mouseleave={() => activeLessonTooltip = null} on:click={(event) => state.status === 'busy' ? openClickedLesson(event, state.teacher, cell.date, row.slot, state.lessons) : (state.status === 'free' || state.status === 'window' || state.status === 'no-lessons') && openSlotReplacementPick(state.teacher, cell.date, row.slot)} on:keydown={(event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target === event.currentTarget && state.status !== 'error') { event.preventDefault(); state.status === 'busy' ? openClickedLesson(event, state.teacher, cell.date, row.slot, state.lessons) : openSlotReplacementPick(state.teacher, cell.date, row.slot); } }}>
                              <span class="viewer-line-entity" title={lane.entity.label}>{formatShortName(lane.entity.label)}:</span>
                              {#if state.status === 'busy'}
                                {#if showSubjects || showGroups || showAuditoriums}<div class="viewer-line-lessons">
                                  {#if showSubjects}<div class="sub-metadata-line sub-subjects">{#each state.lessons as lesson, lessonIndex (lessonIndex)}<span class="sub-metadata-item" data-lesson-index={lessonIndex} title={lesson.discipline}>{lesson.discipline}</span>{/each}</div>{/if}
                                  {#if showGroups}<div class="sub-metadata-line sub-groups">{#each state.lessons as lesson, lessonIndex (lessonIndex)}{#if lesson.group}<span class="sub-metadata-item" data-lesson-index={lessonIndex} title={lesson.group}>{lesson.group}{#if lesson.subgroup} · подгр. {lesson.subgroup}{/if}</span>{/if}{/each}</div>{/if}
                                  {#if showAuditoriums}<div class="sub-metadata-line sub-auditoriums">{#each state.lessons as lesson, lessonIndex (lessonIndex)}{#if lesson.auditorium}<span class="sub-metadata-item" data-lesson-index={lessonIndex} title={`ауд. ${lesson.auditorium}`}>ауд. {lesson.auditorium}</span>{/if}{/each}</div>{/if}
                                </div>{/if}
                              {:else}
                                <span class="sub-status-text">{state.status === 'free' ? 'Свободен' : state.status === 'window' ? `Окно (${formatPairCount(state.windowPairs)})` : state.status === 'error' ? 'Нет данных' : 'Нет занятий сегодня'}</span>
                              {/if}
                            </div>
                          {/if}
                        {/each}
                        {#if visibleLanes.length === 0}<span class="sub-empty-cell-note">Нет преподавателей для отображения</span>{/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        </div>
      </section>
    {/each}
  {/if}
</PlannerPageFrame>

{#if slotReplacementPick}
  <div class="sub-modal-backdrop" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) slotReplacementPick = null; }} on:keydown={(event) => event.key === 'Escape' && (slotReplacementPick = null)}>
    <div class="sub-modal slot-replacement-modal" role="dialog" aria-modal="true" aria-labelledby="slot-replacement-title">
      <button class="sub-modal-close" type="button" aria-label="Закрыть" on:click={() => slotReplacementPick = null}><AppIcon name="close" size={18} /></button>
      <span class="section-kicker">ПОДБОР ЗАМЕНЫ</span>
      <h2 id="slot-replacement-title">Кого заменить этим преподавателем?</h2>
      <p class="sub-modal-context"><strong>Заменяющий: {slotReplacementPick.replacement.label}</strong><br />Дата и пара уже заданы выбранной клеткой. Выберите преподавателя и занятие.</p>
      <div class="sub-candidate-list slot-replacement-target-list">
        {#each slotReplacementTargets(slotReplacementPick) as target (target.teacher.id + ':' + String(target.lesson.rawEvent.lessonOid ?? target.lesson.discipline + ':' + (target.lesson.group ?? '') + ':' + (target.lesson.subgroup ?? '')))}
          {@const targetKey = `${target.teacher.id}:${String(target.lesson.rawEvent.lessonOid ?? target.lesson.discipline + ':' + (target.lesson.group ?? '') + ':' + (target.lesson.subgroup ?? ''))}`}
          <button type="button" class="sub-candidate slot-replacement-target" class:is-picked={slotReplacementPick.target && slotTargetKey(slotReplacementPick.target) === targetKey} aria-pressed={Boolean(slotReplacementPick.target && slotTargetKey(slotReplacementPick.target) === targetKey)} on:click={() => slotReplacementPick && (slotReplacementPick = { ...slotReplacementPick, target })}>
            <span><strong>{target.teacher.label}</strong><small>{target.lesson.discipline}{#if target.lesson.kindOfWork} · {target.lesson.kindOfWork}{/if}{#if target.lesson.group} · {target.lesson.group}{#if target.lesson.subgroup} / подгр. {target.lesson.subgroup}{/if}{/if}{#if target.lesson.auditorium} · ауд. {target.lesson.auditorium}{/if}</small></span>
            <b>{slotReplacementPick.target && slotTargetKey(slotReplacementPick.target) === targetKey ? 'Выбрано' : 'Выбрать'}</b>
          </button>
        {:else}<div class="confirmed-replacements-empty"><strong>На эту пару нет занятий для замены</strong><p>Выберите свободного преподавателя в другом слоте расписания.</p></div>{/each}
      </div>
      {#if slotReplacementPick.target}
        <div class="slot-replacement-confirm"><div><span>Будет заменять · {formatDate(slotReplacementPick.date)}, {slotReplacementPick.slot.number}-я пара · {slotReplacementPick.slot.start}–{slotReplacementPick.slot.end}</span><strong>{slotReplacementPick.target.teacher.label} → {slotReplacementPick.replacement.label}</strong><small>{slotReplacementPick.target.lesson.discipline}{#if slotReplacementPick.target.lesson.group} · {slotReplacementPick.target.lesson.group}{#if slotReplacementPick.target.lesson.subgroup} / подгр. {slotReplacementPick.target.lesson.subgroup}{/if}{/if}</small></div><button type="button" class="primary-button" disabled={savingReplacement} on:click={confirmSlotReplacement}>{savingReplacement ? 'Сохраняем…' : 'Подтвердить замену'}</button></div>
      {/if}
    </div>
  </div>
{/if}

{#if selectedLesson}
  <div class="sub-modal-backdrop" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) selectedLesson = null; }} on:keydown={(event) => event.key === 'Escape' && (selectedLesson = null)}>
    <div class="sub-modal" role="dialog" aria-modal="true" aria-labelledby="replacement-title">
      <button class="sub-modal-close" type="button" aria-label="Закрыть" on:click={() => selectedLesson = null}><AppIcon name="close" size={18} /></button>
      <span class="section-kicker">ПОДБОР ЗАМЕНЫ</span>
      <h2 id="replacement-title">{selectedLesson.lesson.discipline}</h2>
      <p class="sub-modal-context">{selectedLesson.teacher.label} · {selectedLesson.lesson.group ?? 'группа не указана'}<br />{formatDate(selectedLesson.date, { weekday: 'long', day: 'numeric', month: 'long' })}, {selectedLesson.slot.start}–{selectedLesson.slot.end}</p>
      <div class="sub-candidate-tabs" role="tablist" aria-label="Способ подбора преподавателя">
        <button type="button" class:active={candidateMode === 'department'} aria-pressed={candidateMode === 'department'} on:click={() => candidateMode = 'department'}>Кафедра</button>
        <button type="button" class:active={candidateMode === 'topic'} aria-pressed={candidateMode === 'topic'} on:click={() => candidateMode = 'topic'}>Тематическая группа</button>
        <button type="button" class:active={candidateMode === 'other'} aria-pressed={candidateMode === 'other'} on:click={() => candidateMode = 'other'}>Другой преподаватель</button>
      </div>

      {#if candidateMode === 'department'}
        <div class="sub-candidate-list">
          {#each departmentCandidates as candidate (candidate.person.id)}
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status === 'busy' || candidate.status === 'error' || candidate.status === 'loading'} on:click={() => selectReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong><small>{candidate.person.description}</small>{#if candidate.status === 'busy' && candidateBusyText(candidate)}<small class="candidate-busy-detail">Занят: {candidateBusyText(candidate)}</small>{/if}</span><b>{candidateStatusText(candidate)}</b>
            </button>
          {:else}<p class="field-hint">Кроме заменяемого преподавателя на кафедре больше никого нет.</p>{/each}
        </div>
      {:else if candidateMode === 'topic'}
        <div class="sub-topic-select"><CustomSelect ariaLabel="Тематическая группа преподавателей" value={topicId} placeholder="Выберите тематическую группу" options={[{ value: '', label: 'Выберите тематическую группу' }, ...COMMISSION_GROUPS.map((group) => ({ value: group.id, label: group.label, extra: String(group.people.length) }))]} on:change={(event) => chooseTopic(event.detail)} /></div>
        {#if topicLoading}<p class="sub-loading-note">Проверяю расписание участников группы…</p>{/if}
        <div class="sub-candidate-list">
          {#each topicCandidates as candidate (candidate.person.id)}
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons'} on:click={() => selectReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong>{#if candidate.status === 'busy' && candidateBusyText(candidate)}<small class="candidate-busy-detail">Занят: {candidateBusyText(candidate)}</small>{/if}</span><b>{candidateStatusText(candidate)}</b>
            </button>
          {:else}{#if topicId && !topicLoading}<p class="field-hint">В этой группе нет других участников.</p>{/if}{/each}
        </div>
      {:else}
        <SearchField type="person" placeholder="Найти преподавателя по ФИО" onPick={addOther} />
        {#if otherLoading}<p class="sub-loading-note">Проверяю расписание…</p>{/if}
        <div class="sub-candidate-list">
          {#each otherCandidates as candidate (candidate.person.id)}
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons'} on:click={() => selectReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong><small>{candidate.person.description}</small>{#if candidate.status === 'busy' && candidateBusyText(candidate)}<small class="candidate-busy-detail">Занят: {candidateBusyText(candidate)}</small>{/if}</span><b>{candidateStatusText(candidate)}</b><i role="button" tabindex="0" aria-label={`Убрать ${candidate.person.label}`} on:click|stopPropagation={() => removeOther(candidate.person.id)} on:keydown={(event) => event.key === 'Enter' && removeOther(candidate.person.id)}><AppIcon name="close" size={16} /></i>
            </button>
          {/each}
        </div>
      {/if}
      {#if notice}<p class="sub-notice" role="status">{notice}</p>{/if}
      <p class="sub-modal-footnote">Зелёный — свободен без окон · жёлтый — свободен в окно · красный — сегодня нет пар. Выбор помогает согласовать замену и не меняет исходное расписание.</p>
      <div class="sub-confirm-bar">
        <div>{#if pickedReplacement}<span>Замена · {formatDate(selectedLesson.date)}, {selectedLesson.slot.number}-я пара · {selectedLesson.slot.start}–{selectedLesson.slot.end}</span><strong>{selectedLesson.teacher.label} → {pickedReplacement.label}</strong><small>{selectedLesson.lesson.discipline}{#if selectedLesson.lesson.group} · {selectedLesson.lesson.group}{#if selectedLesson.lesson.subgroup} / подгр. {selectedLesson.lesson.subgroup}{/if}{/if}</small>{:else}<span>Сначала выберите свободного преподавателя</span>{/if}</div>
        <button type="button" class="primary-button" disabled={!pickedReplacement || savingReplacement} on:click={saveConfirmedReplacement}>{savingReplacement ? 'Сохраняем…' : 'Подтвердить замену'}</button>
      </div>
    </div>
  </div>
{/if}

{#if showConfirmedReplacements}
  <div class="sub-modal-backdrop" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) showConfirmedReplacements = false; }} on:keydown={(event) => event.key === 'Escape' && (showConfirmedReplacements = false)}>
    <div class="sub-modal confirmed-replacements-modal" role="dialog" aria-modal="true" aria-labelledby="confirmed-replacements-title">
      <button class="sub-modal-close" type="button" aria-label="Закрыть" on:click={() => showConfirmedReplacements = false}><AppIcon name="close" size={18} /></button>
      <span class="section-kicker">ЗАМЕНЫ · СПИСОК</span>
      <h2 id="confirmed-replacements-title">Выбранные замены</h2>
      <p class="sub-modal-context">Общий список замен кафедры. Подтверждённые назначения сразу видны коллегам с доступом к планированию.</p>
      {#if confirmedReplacements.length}
        <div class="confirmed-replacements-list">
          {#each [...confirmedReplacements].sort((a, b) => a.date.localeCompare(b.date) || a.slot.number - b.slot.number) as item (item.key)}
            <article class="confirmed-replacement-card">
              <div class="confirmed-replacement-date"><strong>{formatDate(item.date, { weekday: 'short', day: 'numeric', month: 'long' })}</strong><span>{item.slot.number} пара · {item.slot.start}–{item.slot.end}</span></div>
              <div class="confirmed-replacement-detail"><span>{item.lesson.discipline}{#if item.lesson.group} · {item.lesson.group}{#if item.lesson.subgroup} / подгр. {item.lesson.subgroup}{/if}{/if}</span><strong><small>Вместо:</small> {item.originalTeacher.label} <i>→</i> <small>замещает:</small> {item.replacement.label}</strong><small class="replacement-status" class:replacement-status-confirmed={item.status === 'confirmed'}>{item.status === 'confirmed' ? 'Подтверждена' : 'Ожидает подтверждения'}</small>
                {#if item.issues?.length}<small class="replacement-issues">{#each item.issues as issue}<span>{issue.kind === 'unknown_schedule' ? 'Не удалось проверить актуальность расписания.' : issue.kind === 'source_conflict' ? `У преподавателя есть занятие ${issue.start ?? ''}–${issue.end ?? ''}: ${issue.lesson ?? ''}` : 'Обнаружен конфликт с другой заменой.'}</span>{/each}</small>{/if}
                {#if item.conflictHash}<label class="replacement-reason-label">Причина подтверждения<input type="text" bind:value={confirmationReasons[item.key]} maxlength="2000" placeholder="Укажите причину" /></label><button type="button" class="primary-button replacement-confirm-button" disabled={!confirmationReasons[item.key]?.trim()} on:click={() => confirmPendingReplacement(item)}>Подтвердить с причиной</button>{:else if item.status === 'selected'}{#if item.serverMessage}<small class="replacement-issues">{item.serverMessage}</small>{/if}<button type="button" class="replacement-retry-button" on:click={() => confirmPendingReplacement(item)}>Проверить и подтвердить</button>{/if}
              </div>
              <button type="button" aria-label={`Удалить замену ${item.originalTeacher.label} на ${item.replacement.label}`} on:click={() => removeConfirmedReplacement(item.key)}><AppIcon name="close" size={18} /></button>
            </article>
          {/each}
        </div>
      {:else}
        <div class="confirmed-replacements-empty"><AppIcon name="arrow-up-right" size={18} /><strong>Пока нет выбранных замен</strong><p>Выберите занятие в таблице, затем отметьте преподавателя и подтвердите замену.</p></div>
      {/if}
    </div>
  </div>
{/if}

{#if activeLessonTooltip}
  {@const item = activeLessonTooltip}
  {@const lesson = item.lesson}
  <div class="custom-tooltip sub-lesson-tooltip" style="left:-9999px;top:-9999px" use:positionSubTooltip={item.targetRect} role="tooltip">
    <div class="tooltip-header">
      <span class="tooltip-time">{formatDate(item.date, { weekday: 'short', day: 'numeric', month: 'short' })} · {item.slot.number} пара ({item.slot.start}–{item.slot.end})</span>
      <span class="tooltip-badge status-selected">{item.teacher.label}</span>
    </div>
    <div class="tooltip-body"><div class="tooltip-section"><div class="tooltip-entity-card card-busy">
      <div class="entity-head"><strong class="entity-title">{lesson.discipline}</strong>{#if lesson.kindOfWork}<span class="entity-badge">{lesson.kindOfWork}</span>{/if}</div>
      <div class="entity-desc"><div class="tooltip-meta-stack">
        {#if lesson.group}<div class="tooltip-meta-line"><span class="party-label">Группа:</span><strong>{lesson.group}{#if lesson.subgroup} (подгр. {lesson.subgroup}){/if}</strong></div>{/if}
        {#if lesson.auditorium}<div class="tooltip-meta-line"><span class="party-label">Аудитория:</span><strong>ауд. {lesson.auditorium}{#if lesson.building} ({lesson.building}){/if}</strong></div>{/if}
        {#if lesson.lecturer}<div class="tooltip-meta-line"><span class="party-label">Преподаватель:</span><strong>{lesson.lecturer}</strong></div>{/if}
      </div></div>
    </div></div></div>
  </div>
{/if}

<style>
  :global(.workspace.substitution-workspace){max-width:1600px;padding-bottom:155px}
  .substitution-legend{gap:9px 20px;padding:0 2px;color:#66796f;font-size:10px;font-weight:700}.substitution-legend span{display:flex;align-items:center;gap:6px}.sub-legend-dot{display:inline-block;width:11px;height:11px;border-radius:3px}.sub-legend-dot.free{background:#eaf4ed;border:1px solid #c9e6d2}.sub-legend-dot.window{background:#fdfaf0;border:1px solid #f2e2b6}.sub-legend-dot.no-lessons{background:#fde8e8;border:1px solid #f6c0c0}.sub-legend-dot.busy{background:#edf1ee;border:1px solid #dbe2dd}.sub-display-options{display:flex;flex:1 1 100%;flex-direction:row;align-items:center;justify-content:space-between;gap:12px;width:100%;margin-left:0}.sub-status-options{display:flex;align-items:center;justify-content:flex-start;flex-wrap:wrap;gap:7px}.sub-detail-options{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:5px;margin-left:auto}.sub-display-option{display:flex;align-items:center;gap:6px;border:1px solid #dbe6dc;border-radius:7px;background:#fff;color:#718279;padding:6px 9px;font-size:10px;font-weight:800;white-space:nowrap;cursor:pointer;transition:background .12s,border-color .12s,color .12s}.sub-display-option.active{background:#eaf4ed;border-color:#c9e6d2;color:#286247}.sub-display-option input{width:13px;height:13px;margin:0;accent-color:#38886c}.sub-lesson-tooltip{z-index:1200;min-width:260px}
  .sub-schedule-table{min-width:1380px}.sub-schedule-table .table-row{grid-template-columns:86px repeat(6,minmax(215px,1fr));border-top:2px solid #dce5dc}.sub-schedule-table .table-row:not(.table-head){border-top-color:#cbd7ce}.sub-schedule-table .table-row.table-head{border-top:0}.sub-schedule-table .table-row>div+div{border-left:2px solid #cbd7ce}.sub-schedule-table .table-head>div{border-color:#cbd7ce}.sub-schedule-cell{padding:4px 5px}.sub-empty-lines{flex:1;justify-content:center}.sub-empty-cell-note{display:block;padding:8px;color:#89968d;text-align:center;font-size:10px;font-weight:600}.sub-teacher-line{align-items:center;flex-wrap:nowrap;gap:5px}.sub-teacher-line.details-lines{align-items:stretch;flex-direction:column;gap:3px}.sub-teacher-line.details-lines .viewer-line-entity{flex:0 0 auto;max-width:100%}.sub-teacher-line[role="button"]{cursor:pointer}.sub-teacher-line[role="button"]:hover{filter:brightness(.98)}.sub-teacher-line .viewer-line-entity{flex:0 1 112px;max-width:112px}.sub-teacher-line .viewer-line-lessons{flex:1 1 0;width:0;min-width:0}.sub-teacher-line.details-lines .viewer-line-lessons{flex:none;width:100%}.sub-teacher-line.sub-free{background:#eaf4ed;border:1px solid #c9e6d2;color:#235c3b}.sub-teacher-line.sub-window{background:#fdfaf0;border:1px solid #f2e2b6;color:#7a541c}.sub-teacher-line.sub-no-lessons{background:#fff0f0;border:1px solid #f6c0c0;color:#a32a2a}.sub-teacher-line.sub-error{background:#f2f4f2;border:1px solid #dbe2dd;color:#718279}.sub-metadata-line{display:flex;align-items:baseline;gap:4px;min-width:0;overflow:hidden;font-size:9px;line-height:1.25}.sub-metadata-item{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#344d40}.sub-metadata-item:not(:last-child)::after{content:' ·';color:#71887b}.sub-groups .sub-metadata-item{color:#71887b}.sub-status-text{overflow:hidden;text-overflow:ellipsis;font-size:9px;font-weight:700;white-space:nowrap}
  .sub-state{background:white;border:1px solid #e4eae3;border-radius:10px;padding:28px;color:#6c7f74;font-size:13px}.sub-state.error{color:#9d3838;background:#fff8f8;border-color:#f1d6d6}
  .sub-modal-backdrop{position:fixed;inset:0;z-index:1100;background:rgba(18,39,31,.42);display:grid;place-items:center;padding:18px}.sub-modal{position:relative;width:min(610px,100%);max-height:min(86vh,800px);overflow:auto;background:#fff;border:1px solid #dce7df;border-radius:14px;padding:26px;box-shadow:0 24px 70px rgba(17,47,35,.24)}.sub-modal-close{position:absolute;right:16px;top:13px;border:0;background:transparent;color:#75877d;font-size:25px}.sub-modal h2{margin:7px 35px 5px 0;color:#214b3b;font-size:23px;letter-spacing:-.04em}.sub-modal-context{margin:0 0 18px;color:#75867c;font-size:11px;line-height:1.7}.sub-candidate-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:4px;border-radius:8px;background:#f1f5f1;margin:15px 0}.sub-candidate-tabs button{border:0;background:transparent;border-radius:6px;padding:8px 10px;color:#718279;font-size:10px;font-weight:800}.sub-candidate-tabs button.active{background:#fff;color:#275b47;box-shadow:0 1px 4px #173e291a}.sub-topic-select{margin:0 0 10px}.sub-candidate-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}.sub-candidate{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;text-align:left;border:1px solid #e3eae4;border-radius:7px;padding:9px 10px;background:#fff;color:#365543}.sub-candidate.is-picked{border-color:#6fa88a!important;box-shadow:inset 3px 0 #4d9472}.sub-candidate>span{display:flex;flex-direction:column;gap:3px;min-width:0}.sub-candidate strong{font-size:11px}.sub-candidate small{font-size:8px;color:#819187}.sub-candidate small.candidate-busy-detail{color:#52685b;font-size:9px;font-weight:700}.sub-candidate b{font-size:8px;white-space:nowrap;border-radius:4px;padding:5px 7px}.sub-candidate.status-free b{background:#dcefe1}.sub-candidate.status-window b{background:#faeec7}.sub-candidate.status-no-lessons b{background:#fbdede}.sub-candidate:disabled{cursor:default;opacity:.85}.sub-candidate:not(:disabled):hover{filter:brightness(.97)}.sub-candidate i{font-style:normal;font-size:17px;color:#829187}.sub-loading-note{margin:10px 0 0;color:#79897f;font-size:10px}.sub-notice{background:#eef7f0;border:1px solid #cfe6d3;border-radius:7px;padding:10px;color:#28623c;font-size:11px}.sub-modal-footnote{margin:15px 0 0;color:#849289;font-size:9px;line-height:1.6}
  .confirmed-replacements-trigger{position:fixed;right:30px;bottom:24px;z-index:1050;display:flex;align-items:center;gap:11px;border:1px solid #2d6b4f;border-radius:12px;background:#193c31;color:#fff;padding:10px 14px;box-shadow:0 14px 35px rgba(18,58,40,.28);text-align:left;transition:transform .15s,background .15s}.confirmed-replacements-trigger:hover{background:#245744;transform:translateY(-2px)}.confirmed-replacements-trigger .selection-count{flex:none}.confirmed-replacements-trigger>span:nth-child(2){display:flex;flex-direction:column;gap:2px;min-width:120px}.confirmed-replacements-trigger strong{font-size:11px}.confirmed-replacements-trigger small{font-size:9px;color:#b4d5bd}.confirmed-replacements-open{display:grid;place-items:center;width:30px;height:30px;border-radius:7px;background:#335a49;color:#d8efdc;font-size:16px}
  .sub-board-notice{margin:0 0 12px;padding:9px 12px;border:1px solid #cfe6d3;border-radius:7px;background:#eef7f0;color:#28623c;font-size:11px}
  .sub-confirm-bar{position:sticky;bottom:-26px;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:14px;margin:15px -26px -26px;padding:13px 26px 18px;border-top:1px solid #e4ebe5;background:linear-gradient(180deg,rgba(255,255,255,.96),#fff 24%)}.sub-confirm-bar>div{display:flex;flex-direction:column;gap:3px;min-width:0;color:#78897e;font-size:9px}.sub-confirm-bar strong{overflow:hidden;color:#315946;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.sub-confirm-bar .primary-button{flex:0 0 auto;padding:11px 14px;font-size:10px;box-shadow:none}.sub-confirm-bar .primary-button:disabled{opacity:.7}
  .confirmed-replacements-modal{max-width:720px}.confirmed-replacements-list{display:flex;flex-direction:column;gap:8px;max-height:min(54vh,500px);overflow:auto}.confirmed-replacement-card{display:grid;grid-template-columns:minmax(125px,.75fr) minmax(0,2fr) 28px;align-items:center;gap:12px;padding:12px;border:1px solid #dfe9e1;border-radius:9px;background:#fbfdfb}.confirmed-replacement-date,.confirmed-replacement-detail{display:flex;flex-direction:column;gap:4px;min-width:0}.confirmed-replacement-date strong,.confirmed-replacement-detail strong{color:#315946;font-size:10px}.confirmed-replacement-date span,.confirmed-replacement-detail>span{color:#7d8e83;font-size:9px;line-height:1.4}.confirmed-replacement-detail strong{overflow-wrap:anywhere}.confirmed-replacement-detail i{color:#81ad92;font-style:normal;padding:0 3px}.confirmed-replacement-card>button{width:27px;height:27px;border:0;border-radius:6px;background:#f5e9e7;color:#a45b55;font-size:18px}.confirmed-replacements-empty{display:grid;justify-items:center;gap:8px;padding:35px 20px;border:1px dashed #dce8de;border-radius:9px;background:#fbfdfb;text-align:center}.confirmed-replacements-empty>span{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#eaf4ed;color:#579374;font-size:20px}.confirmed-replacements-empty strong{color:#385e49;font-size:12px}.confirmed-replacements-empty p{max-width:340px;margin:0;color:#819187;font-size:10px;line-height:1.6}.confirmed-replacements-clear{display:block;margin:13px 0 0 auto;border:0;background:transparent;color:#a45b55;font-size:10px;font-weight:800}
  .slot-replacement-modal{max-width:720px}.slot-replacement-modal .sub-modal-context strong{color:#315946}.slot-replacement-target{min-height:57px}.slot-replacement-target small{font-size:9px;line-height:1.45}.slot-replacement-target b{flex:none;background:#eef6ef;color:#2d6d54;padding:7px 9px}.slot-replacement-target.is-picked{background:#f1f8f2}.slot-replacement-confirm{position:sticky;bottom:-26px;display:flex;align-items:center;justify-content:space-between;gap:14px;margin:15px -26px -26px;padding:13px 26px 18px;border-top:1px solid #e4ebe5;background:linear-gradient(180deg,rgba(255,255,255,.96),#fff 24%)}.slot-replacement-confirm>div{display:flex;flex-direction:column;gap:3px;min-width:0;color:#78897e;font-size:9px}.slot-replacement-confirm strong{overflow:hidden;color:#315946;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.slot-replacement-confirm .primary-button{flex:0 0 auto;padding:11px 14px;font-size:10px;box-shadow:none}
  .substitution-help{flex:1 1 100%;width:100%;margin:2px 0 0;color:#6f8176;font-size:11px;font-weight:500;line-height:1.5}.substitution-help strong{color:#315946;font-weight:800}.sub-display-options{flex-wrap:nowrap;gap:6px}.sub-status-options,.sub-detail-options{flex-wrap:nowrap;gap:4px}.sub-display-option{font-size:10px;padding:6px 7px;gap:4px}.sub-status-options .sub-display-option input,.sub-detail-options .sub-display-option input{flex:0 0 13px}.sub-status-text{font-size:10px;line-height:1.35}.sub-metadata-line{font-size:10px}.sub-candidate strong{font-size:12px}.sub-candidate small{font-size:10px;line-height:1.4}.sub-candidate b{font-size:9px}.sub-modal-context{font-size:12px}.sub-modal-footnote{font-size:10px}.confirmed-replacement-date strong,.confirmed-replacement-detail strong{font-size:11px}.confirmed-replacement-date span,.confirmed-replacement-detail>span{font-size:10px}.confirmed-replacements-empty p{font-size:11px}.slot-replacement-target{min-height:60px}.slot-replacement-target small{font-size:10px}.slot-replacement-target b{font-size:10px}.slot-replacement-confirm>div{font-size:10px}.slot-replacement-confirm strong{font-size:11px}.slot-replacement-confirm small,.sub-confirm-bar small{color:#718579;font-size:10px;line-height:1.35}.sub-confirm-bar>div{font-size:10px}.sub-confirm-bar strong{font-size:11px}.sub-teacher-line[role="button"]:focus-visible{outline:3px solid #82bca5;outline-offset:1px;position:relative;z-index:1}.sub-teacher-line:not(.sub-error):hover{border-color:#80b59a;box-shadow:0 1px 4px rgba(36,95,80,.12);filter:none}
  .replacement-status{align-self:flex-start;padding:3px 6px;border-radius:5px;background:#f4f0e3;color:#78622b;font-size:9px;font-weight:800}.replacement-status-confirmed{background:#eaf4ed;color:#286247}.replacement-issues{display:flex;flex-direction:column;gap:3px;color:#8a6127;font-size:10px;line-height:1.4}.replacement-reason-label{display:grid;gap:5px;color:#65776c;font-size:10px;font-weight:700}.replacement-reason-label input{min-height:36px;padding:7px 9px;border:1px solid #dbe6dc;border-radius:6px;background:#fff;color:#315946;font:inherit}.replacement-confirm-button,.replacement-retry-button{align-self:flex-start;padding:8px 11px;font-size:10px}.replacement-retry-button{border:1px solid #dce8de;border-radius:6px;background:#f3f7f3;color:#315946;font-weight:800;cursor:pointer}
  @media(max-width:900px){.sub-display-options{align-items:flex-start;flex-direction:column;flex-wrap:wrap}.sub-status-options,.sub-detail-options{flex-wrap:wrap}.sub-detail-options{margin-left:0;justify-content:flex-start}}
  @media(max-width:560px){:global(.workspace.substitution-workspace){padding-bottom:125px}.sub-modal{padding:20px}.sub-candidate-tabs button{flex:1}.substitution-legend{gap:8px 12px}.sub-confirm-bar{bottom:-20px;margin:12px -20px -20px;padding:12px 20px 14px;align-items:stretch;flex-direction:column}.sub-confirm-bar .primary-button{width:100%;justify-content:center}.confirmed-replacement-card{grid-template-columns:minmax(0,1fr) 28px}.confirmed-replacement-date{grid-column:1}.confirmed-replacement-detail{grid-column:1;grid-row:2}.confirmed-replacement-card>button{grid-column:2;grid-row:1 / span 2}.confirmed-replacements-trigger{right:14px;bottom:max(14px,env(safe-area-inset-bottom));padding:8px 10px;gap:8px}.confirmed-replacements-trigger>span:nth-child(2){min-width:0}.confirmed-replacements-trigger .selection-count{width:32px;height:32px;font-size:17px}.slot-replacement-confirm{bottom:-20px;margin:12px -20px -20px;padding:12px 20px 14px;align-items:stretch;flex-direction:column}.slot-replacement-confirm .primary-button{width:100%;justify-content:center}}
</style>
