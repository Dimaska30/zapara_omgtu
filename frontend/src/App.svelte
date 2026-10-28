<script lang="ts">
  import { onMount } from 'svelte';
  import CustomSelect from './CustomSelect.svelte';
  import SearchField from './SearchField.svelte';
  import Substitutions from './Substitutions.svelte';
  import Admin from './Admin.svelte';
  import AppIcon from './AppIcon.svelte';
  import TeacherSchedule from './TeacherSchedule.svelte';
  import AuditoriumSchedule from './AuditoriumSchedule.svelte';
  import { account, accountChecking, restoreAccount, setAccount, mayPlan, unreadNotifications } from './lib/account';
  import PlannerPageFrame from './PlannerPageFrame.svelte';
  import PlannerFilterBar from './PlannerFilterBar.svelte';
  import PlannerToolbar from './PlannerToolbar.svelte';
  import {
    AUDITORIUM_TYPE_CATEGORIES,
    DEFAULT_BUILDINGS,
    SLOTS,
    addDays,
    buildViewerWeeks,
    buildWeeks,
    checkAuditoriumsAvailability,
    formatDate,
    formatPairCount,
    formatLessonKindShort,
    formatShortName,
    getAuditoriums,
    getBuildings,
    getBuildingSchedule,
    getGroupCatalog,
    getSchedule,
    getPlannedEvents,
    mergePlannedEvents,
    matchesAuditoriumType,
    search,
    toIso,
    type ApiItem,
    type AuditoriumAvailabilityInfo,
    type AuditoriumItem,
    type Building,
    type Cell,
    type Group,
    type ScheduleViewerEntity,
    type SearchItem,
    type Slot,
    type ViewerLessonDetail,
    type ViewerWeek,
    type Week,
    type WindowStatus
  } from './lib/schedule';
  import { COMMISSION_GROUPS } from './lib/commission';

  type Page = 'home' | 'consultations' | 'retakes' | 'substitutions' | 'meetings' | 'schedule' | 'teachers' | 'auditoriums' | 'admin';
  type PlanKind = 'consultation' | 'retake' | 'meeting';
  type PlanDraft = { id: string; version: number; kind: PlanKind; settings: Record<string, any>; slots: any[] };
  type PlanSaveState = 'idle' | 'loading' | 'saving' | 'saved' | 'error';
  type LoadedSchedule = {
    start: string;
    finish: string;
    teacherEvents: ApiItem[];
    groupEvents: Map<string, ApiItem[]>;
    groups: Group[];
    candidates: SearchItem[];
    commissionEvents: Map<string, ApiItem[]>;
    failedIds: Set<string>;
    mode: 'availability' | 'substitution' | 'meeting';
    auditoriumEvents: Map<string, ApiItem[]>;
    auditoriums: SearchItem[];
  };
  const sections: { page: Page; name: string; description: string; icon: 'calendar' | 'teacher' | 'consultations' | 'retakes' | 'substitutions' | 'meetings' | 'building'; guest: boolean }[] = [
    { page: 'schedule', name: 'Расписание групп', description: 'Посмотрите занятия одной или нескольких групп на выбранные даты.', icon: 'calendar', guest: true },
    { page: 'teachers', name: 'Расписание преподавателей', description: 'Найдите преподавателя по фамилии и откройте его занятия.', icon: 'teacher', guest: true },
    { page: 'auditoriums', name: 'Свободные аудитории', description: 'Посмотрите свободные помещения корпуса по дням и парам.', icon: 'building', guest: true },
    { page: 'consultations', name: 'Консультации', description: 'Найдите свободное время преподавателя и выбранных групп.', icon: 'consultations', guest: false },
    { page: 'retakes', name: 'Пересдачи', description: 'Подберите время для пересдачи или работы комиссии.', icon: 'retakes', guest: false },
    { page: 'substitutions', name: 'Замены', description: 'Найдите занятие и подберите преподавателя для замены.', icon: 'substitutions', guest: false },
    { page: 'meetings', name: 'Встречи', description: 'Найдите время, когда все выбранные преподаватели свободны.', icon: 'meetings', guest: false }
  ];
  const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  let currentDateIso = toIso(new Date());

  let page: Page = 'home';
  let activePlan: PlanDraft | null = null;
  let planSaveState: PlanSaveState = 'idle';
  let planSaveMessage = '';
  let draftHydrated = false;
  let pendingPlanRestore: any[] | null = null;
  let draftSaveTimer: number | null = null;
  let savedDraftSignature = '';
  let draftSaveChain: Promise<void> = Promise.resolve();
  let activationToken = '';
  let uiPage: Page = 'home';
  $: canPlan = mayPlan($account);
  $: if (!$accountChecking && !canPlan && ['retakes', 'consultations', 'substitutions', 'meetings'].includes(page)) { invalidate(); page = 'schedule'; void loadViewerDepartmentGroups().then(generateScheduleView); }
  $: uiPage = page;
  let teacher: SearchItem | null = null;
  let retakeMode: 'first' | 'commission' = 'first';
  let commissionChoice: 'people' | 'group' = 'people';
  let commissionGroupId = '';
  let mercy = false;
  let commissionTeachers: SearchItem[] = [];
  let meetingTeachers: SearchItem[] = [];
  let meetingError = '';
  let committeeError = '';
  let groups: Group[] = [];
  let auditoriums: SearchItem[] = [];

  let availableBuildings: Building[] = [...DEFAULT_BUILDINGS];
  let loadingBuildings = false;
  let selectedBuildingOid: number | null = null;
  let selectedAudTypes = new Set<string>();
  let selectedGroupFilter = 'all';
  let showAudFilters = false;
  let buildingAuditoriums: AuditoriumItem[] = [];
  let loadingBuildingAuds = false;

  // Finder modal state
  let showAudModal = false;
  let modalTargetSlotKey = 'all';
  let modalBuildingOid: number | null = 16;
  let modalAudTypes = new Set<string>();
  let modalSearchQuery = '';
  let modalMinCapacity = 0;
  let modalGroupFilter = 'all';
  let modalLoading = false;
  let modalError = '';
  let modalAuditoriumsList: AuditoriumItem[] = [];
  let modalBuildingSchedule: ApiItem[] = [];
  let modalAvailability: AuditoriumAvailabilityInfo[] = [];

  // Selected slots modal state
  let showSelectedModal = false;

  type AssignedAuditorium = {
    id: string;
    name: string;
    number?: string;
    building?: string;
    capacity?: number;
    type?: string;
  };
  let slotAssignedAuditoriums = new Map<string, AssignedAuditorium>();

  function removeSlotAssignedAud(slotKey: string) {
    slotAssignedAuditoriums.delete(slotKey);
    slotAssignedAuditoriums = new Map(slotAssignedAuditoriums);
  }

  // Toast notification
  let toastMessage: string | null = null;
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  function showToast(msg: string) {
    if (toastTimer) clearTimeout(toastTimer);
    toastMessage = msg;
    toastTimer = setTimeout(() => { toastMessage = null; }, 3500);
  }

  // Schedule viewer state
  function viewerWeekStart(date: Date) {
    return addDays(date, -((date.getDay() + 6) % 7));
  }

  const viewerDefaultStart = toIso(viewerWeekStart(new Date()));
  let viewerGroupMode: 'all' | 'selected' = 'all';
  let viewerOnlyWithLessons = true;
  let viewerShowTeacher = false;
  let viewerShowSubject = false;
  let viewerShowAuditorium = true;
  let viewerDepartmentGroups: ScheduleViewerEntity[] = [];
  let viewerCustomGroups: ScheduleViewerEntity[] = [];
  let viewerSelectableGroups: ScheduleViewerEntity[] = [];
  let viewerGroupColumns: { year: string; groups: ScheduleViewerEntity[] }[] = [];
  let viewerSelectedGroupIds = new Set<string>();
  let viewerDisplayEntities: ScheduleViewerEntity[] = [];
  let viewerLoadedEntities: ScheduleViewerEntity[] = [];
  let viewerEventsByEntity = new Map<string, ApiItem[]>();
  let viewerScheduleFailedIds = new Set<string>();
  let viewerScheduleCacheRange = '';
  let viewerGroupCatalogLoading = false;
  let viewerGroupCatalogError = '';
  let viewerGroupCatalogKey = '';
  let viewerGroupCatalogTask: Promise<void> | null = null;
  let viewerStart: string = viewerDefaultStart;
  let viewerFinish: string = toIso(addDays(new Date(`${viewerDefaultStart}T00:00:00`), 12));
  let viewerWeeks: ViewerWeek[] = [];
  let viewerLoading: boolean = false;
  let viewerError: string | null = null;
  let viewerHasGenerated: boolean = false;
  let viewerLoadTimer: number | null = null;
  let viewerRequestId = 0;

  function groupViewerGroupsByYear(groups: ScheduleViewerEntity[]) {
    const columns = new Map<string, ScheduleViewerEntity[]>();
    for (const group of groups) {
      const year = group.label.match(/-(\d{2})\d/u)?.[1] ?? 'Другие';
      const items = columns.get(year) ?? [];
      items.push(group);
      columns.set(year, items);
    }
    return [...columns.entries()]
      .sort(([a], [b]) => a === 'Другие' ? 1 : b === 'Другие' ? -1 : Number(a) - Number(b))
      .map(([year, items]) => ({ year, groups: items }));
  }

  $: viewerSelectableGroups = [...viewerDepartmentGroups, ...viewerCustomGroups];
  $: viewerGroupColumns = groupViewerGroupsByYear(viewerSelectableGroups);

  async function loadViewerDepartmentGroups() {
    const start = viewerStart;
    const finish = viewerFinish;
    const rangeKey = `${start}:${finish}`;
    if (viewerGroupCatalogKey === rangeKey) return;
    if (viewerGroupCatalogTask) {
      await viewerGroupCatalogTask;
      if (viewerGroupCatalogKey === rangeKey) return;
      return loadViewerDepartmentGroups();
    }

    viewerGroupCatalogLoading = true;
    viewerGroupCatalogError = '';
    viewerGroupCatalogTask = (async () => {
      try {
        const foundGroups = await getGroupCatalog();
        const groupsById = new Map<string, ScheduleViewerEntity>();
        for (const group of foundGroups) {
          const label = group.label.trim();
          if (!/^(?:МО|ФИТ)м?-\d+/iu.test(label)) continue;
          if (!group.description.includes('Факультет информационных технологий и компьютерных систем')) continue;
          groupsById.set(group.id, { ...group, label, type: 'group' });
        }
        if (!groupsById.size) throw new Error('Не удалось найти группы МО и ФИТ в расписании ОмГТУ.');

        const oldIds = new Set(viewerDepartmentGroups.map((group) => group.id));
        const groups = [...groupsById.values()].sort((a, b) => a.label.localeCompare(b.label, 'ru'));
        const customIds = new Set(viewerCustomGroups.map((group) => group.id));
        const selectedIds = new Set([...viewerSelectedGroupIds].filter((id) => groupsById.has(id) || customIds.has(id)));
        for (const group of groups) if (!oldIds.has(group.id)) selectedIds.add(group.id);
        viewerDepartmentGroups = groups;
        viewerSelectedGroupIds = selectedIds;
        viewerGroupCatalogKey = rangeKey;
        if (!groups.length) viewerGroupCatalogError = 'В расписании ОмГТУ не найдены группы МО и ФИТ.';
      } catch (cause) {
        viewerGroupCatalogError = cause instanceof Error ? cause.message : 'Не удалось загрузить группы кафедры ПМФИ.';
        viewerDepartmentGroups = [];
        viewerGroupCatalogKey = rangeKey;
      }
    })();
    try { await viewerGroupCatalogTask; }
    finally {
      viewerGroupCatalogTask = null;
      viewerGroupCatalogLoading = false;
    }
  }

  function viewerScheduleEntities(): ScheduleViewerEntity[] {
    return viewerGroupMode === 'all'
      ? viewerDepartmentGroups
      : viewerSelectableGroups.filter((group) => viewerSelectedGroupIds.has(group.id));
  }

  function queueViewerSchedule(delay = 220) {
    viewerRequestId++;
    if (viewerLoadTimer !== null) window.clearTimeout(viewerLoadTimer);
    viewerLoadTimer = window.setTimeout(() => {
      viewerLoadTimer = null;
      if (viewerStart && viewerFinish && viewerStart <= viewerFinish) void generateScheduleView();
    }, delay);
  }

  function addViewerGroup(item: SearchItem) {
    const group: ScheduleViewerEntity = { ...item, type: 'group' };
    const existing = viewerSelectableGroups.find((candidate) => candidate.id === group.id);
    if (!existing) viewerCustomGroups = [...viewerCustomGroups, group];
    viewerGroupMode = 'selected';
    viewerSelectedGroupIds = new Set([...viewerSelectedGroupIds, group.id]);
    queueViewerSchedule();
  }

  function toggleViewerGroup(id: string) {
    const next = new Set(viewerSelectedGroupIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    viewerSelectedGroupIds = next;
    applyViewerGroupSelection();
  }

  function setViewerYearSelection(groups: ScheduleViewerEntity[], checked: boolean) {
    const next = new Set(viewerSelectedGroupIds);
    for (const group of groups) {
      if (checked) next.add(group.id);
      else next.delete(group.id);
    }
    viewerSelectedGroupIds = next;
    applyViewerGroupSelection();
  }

  function setIndeterminate(node: HTMLInputElement, indeterminate: boolean) {
    node.indeterminate = indeterminate;
    return { update(value: boolean) { node.indeterminate = value; } };
  }

  function selectAllViewerGroups(checked: boolean) {
    viewerSelectedGroupIds = new Set(checked ? viewerSelectableGroups.map((group) => group.id) : []);
    applyViewerGroupSelection();
  }

  function applyViewerGroupSelection() {
    const entities = viewerScheduleEntities();
    viewerLoadedEntities = entities;
    applyViewerDisplayFilter();
    queueViewerSchedule();
  }

  function applyViewerDisplayFilter() {
    const allWeeks = buildViewerWeeks(viewerStart, viewerFinish, viewerLoadedEntities, viewerEventsByEntity);
    viewerDisplayEntities = viewerOnlyWithLessons
      ? viewerLoadedEntities.filter((entity) => viewerScheduleFailedIds.has(`${entity.type}:${entity.id}`) || allWeeks.some((week) => week.rows.some((row) => row.cells.some((cell) => cell.lanes.some((lane) => lane.entity.id === entity.id && lane.entity.type === entity.type && lane.lessons.length > 0)))))
      : viewerLoadedEntities;
    viewerWeeks = viewerOnlyWithLessons
      ? buildViewerWeeks(viewerStart, viewerFinish, viewerDisplayEntities, viewerEventsByEntity)
      : allWeeks;
  }

  type ActiveViewerTooltip = {
    lesson: ViewerLessonDetail | null;
    entity: ScheduleViewerEntity;
    slot: Slot;
    date: string;
    targetRect: DOMRect;
  };

  let activeViewerTooltip: ActiveViewerTooltip | null = null;

  function showViewerTooltip(lesson: ViewerLessonDetail, entity: ScheduleViewerEntity, slot: Slot, date: string, event: MouseEvent | FocusEvent) {
    const target = event.currentTarget as HTMLElement | null;
    if (!target) return;
    const targetRect = target.getBoundingClientRect();
    activeViewerTooltip = { lesson, entity, slot, date, targetRect };
  }

  function showViewerStatusTooltip(entity: ScheduleViewerEntity, slot: Slot, date: string, event: MouseEvent | FocusEvent) {
    const target = event.currentTarget as HTMLElement | null;
    if (!target) return;
    activeViewerTooltip = { lesson: null, entity, slot, date, targetRect: target.getBoundingClientRect() };
  }

  function hideViewerTooltip() {
    activeViewerTooltip = null;
  }

  async function generateScheduleView() {
    const requestId = ++viewerRequestId;
    const rangeStart = viewerStart;
    const rangeFinish = viewerFinish;
    if (!rangeStart || !rangeFinish || rangeStart > rangeFinish) return;
    if (viewerGroupCatalogKey !== `${viewerStart}:${viewerFinish}`) {
      await loadViewerDepartmentGroups();
      if (requestId !== viewerRequestId) return;
    }
    const entities = viewerScheduleEntities();
    if (entities.length === 0) {
      viewerLoading = false;
      viewerHasGenerated = false;
      viewerError = null;
      viewerLoadedEntities = [];
      viewerDisplayEntities = [];
      viewerWeeks = [];
      return;
    }
    const cacheKey = `${viewerStart}:${viewerFinish}`;
    if (viewerScheduleCacheRange !== cacheKey) {
      viewerEventsByEntity = new Map();
      viewerScheduleFailedIds = new Set();
      viewerScheduleCacheRange = cacheKey;
    }
    const missingEntities = entities.filter((entity) => {
      const key = `${entity.type}:${entity.id}`;
      return !viewerEventsByEntity.has(key) || viewerScheduleFailedIds.has(key);
    });
    viewerLoading = missingEntities.length > 0;
    viewerError = null;
    try {
      const entityEventsMap = new Map(viewerEventsByEntity);
      const failedIds = new Set(viewerScheduleFailedIds);
      viewerLoadedEntities = entities.filter((entity) => entityEventsMap.has(`${entity.type}:${entity.id}`));
      viewerHasGenerated = viewerLoadedEntities.length > 0;
      applyViewerDisplayFilter();
      await Promise.all(
        missingEntities.map(async (entity) => {
          const key = `${entity.type}:${entity.id}`;
          try {
            const events = await getSchedule(entity.type, entity.id, rangeStart, rangeFinish);
            entityEventsMap.set(key, events);
            failedIds.delete(key);
          } catch (e) {
            console.error(`Failed to load schedule for ${entity.label}:`, e);
            failedIds.add(key);
            entityEventsMap.set(key, []);
          }
          if (requestId !== viewerRequestId) return;
          viewerEventsByEntity = new Map(entityEventsMap);
          viewerScheduleFailedIds = new Set(failedIds);
          viewerLoadedEntities = entities.filter((item) => entityEventsMap.has(`${item.type}:${item.id}`));
          viewerScheduleCacheRange = cacheKey;
          viewerHasGenerated = viewerLoadedEntities.length > 0;
          applyViewerDisplayFilter();
        })
      );
      try {
        const planned = await getPlannedEvents(rangeStart, rangeFinish);
        for (const entity of entities) {
          const key = `${entity.type}:${entity.id}`;
          entityEventsMap.set(key, mergePlannedEvents(entityEventsMap.get(key) ?? [], planned, entity.type, entity.id));
        }
      } catch (planError) {
        console.error('Не удалось загрузить общие записи планирования:', planError);
      }
      viewerLoadedEntities = entities;
      viewerEventsByEntity = entityEventsMap;
      viewerScheduleFailedIds = failedIds;
      viewerScheduleCacheRange = cacheKey;
      applyViewerDisplayFilter();
      viewerHasGenerated = true;
    } catch (e: any) {
      if (requestId === viewerRequestId) viewerError = e?.message ?? 'Не удалось загрузить расписание для выбранных объектов';
    } finally {
      if (requestId === viewerRequestId) viewerLoading = false;
    }
  }

  $: groupsStepNumber = (page === 'retakes' && retakeMode === 'commission') ? '03' : '02';
  $: audStepNumber = (page === 'retakes' && retakeMode === 'commission') ? '04' : (page === 'meetings') ? '02' : '03';
  $: periodStepNumber = (page === 'retakes' && retakeMode === 'commission') ? '05' : (page === 'meetings') ? '03' : '04';

  $: modalTargetSlotDetail = modalTargetSlotKey !== 'all' ? selectedDetails.find((d) => d.cell.key === modalTargetSlotKey) : null;

  $: filteredBuildingAuds = buildingAuditoriums.filter((aud) => {
    if (selectedAudTypes.size > 0 && !matchesAuditoriumType(aud.typeOfAuditorium, selectedAudTypes)) {
      return false;
    }
    return true;
  });

  $: modalFilteredAvailability = modalAvailability.filter((item) => {
    if (!item.freeAll) return false;
    if (modalMinCapacity > 0 && (item.auditorium.amount || 0) < modalMinCapacity) return false;
    if (modalAudTypes.size > 0 && !matchesAuditoriumType(item.auditorium.typeOfAuditorium, modalAudTypes)) return false;
    if (modalSearchQuery.trim()) {
      const q = modalSearchQuery.trim().toLowerCase();
      const name = (item.auditorium.name || '').toLowerCase();
      const num = (item.auditorium.number || '').toLowerCase();
      const type = (item.auditorium.typeOfAuditorium || '').toLowerCase();
      if (!name.includes(q) && !num.includes(q) && !type.includes(q)) return false;
    }
    return true;
  });

  const today = new Date();
  let start = toIso(today);
  const later = new Date(today); later.setDate(later.getDate() + 13);
  let finish = toIso(later);
  let weeks: Week[] = [];
  let selected = new Set<string>();
  let loading = false;
  let error = '';
  let unknownDates = 0;
  let failedCommissionCount = 0;
  let hasGenerated = false;
  let requestController: AbortController | null = null;
  let requestNumber = 0;
  let generateTimer: number | null = null;
  let loadedSchedule: LoadedSchedule | null = null;
  $: selectedCount = selected.size;
  $: selectedDetails = weeks.flatMap((week) => week.rows.flatMap((row) => row.cells.filter((cell) => selected.has(cell.key)).map((cell) => ({ cell, slot: row.slot }))));
  $: selectedCommissionGroup = COMMISSION_GROUPS.find((group) => group.id === commissionGroupId);

  function invalidate() {
    if (generateTimer !== null) window.clearTimeout(generateTimer);
    generateTimer = null;
    hideTooltip();
    showSelectedModal = false;
    showAudModal = false;
    requestController?.abort();
    requestNumber++;
    loading = false;
    weeks = [];
    selected = new Set();
    slotAssignedAuditoriums = new Map();
    hasGenerated = false;
    error = '';
    failedCommissionCount = 0;
    loadedSchedule = null;
    if (activePlan && isPlanningPage(page)) {
      pendingPlanRestore = null;
      draftHydrated = true;
    }
  }

  function planKindFor(target: Page): PlanKind | null {
    return target === 'consultations' ? 'consultation' : target === 'retakes' ? 'retake' : target === 'meetings' ? 'meeting' : null;
  }

  function isPlanningPage(target: Page = page) { return planKindFor(target) !== null; }

  async function planningRequest(path: string, method = 'GET', body?: unknown) {
    if (!$account?.token || !$account.departmentId) throw new Error('Войдите в аккаунт кафедры, чтобы сохранять выбранное.');
    const response = await fetch(`/backend-api/plans${path}`, {
      method,
      headers: { Authorization: `Bearer ${$account.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    if (!response.ok) {
      let payload: any = {};
      try { payload = await response.json(); } catch { /* Keep a readable fallback for empty responses. */ }
      const error = new Error(typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || `Не удалось сохранить план (${response.status}).`) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function restorePlanSettings(settings: Record<string, any>) {
    const searchItems = (value: unknown): SearchItem[] => Array.isArray(value) ? value.filter((item) => item && typeof item.id === 'string' && typeof item.label === 'string') : [];
    if (settings.start) start = String(settings.start);
    if (settings.finish) finish = String(settings.finish);
    if (settings.teacher && typeof settings.teacher.id === 'string') teacher = settings.teacher;
    if (Array.isArray(settings.groups)) groups = searchItems(settings.groups) as Group[];
    if (Array.isArray(settings.auditoriums)) auditoriums = searchItems(settings.auditoriums);
    if (Array.isArray(settings.commissionTeachers)) commissionTeachers = searchItems(settings.commissionTeachers);
    if (Array.isArray(settings.meetingTeachers)) meetingTeachers = searchItems(settings.meetingTeachers);
    if (settings.retakeMode === 'first' || settings.retakeMode === 'commission') retakeMode = settings.retakeMode;
    if (settings.commissionChoice === 'people' || settings.commissionChoice === 'group') commissionChoice = settings.commissionChoice;
    if (typeof settings.commissionGroupId === 'string') commissionGroupId = settings.commissionGroupId;
    if (typeof settings.mercy === 'boolean') mercy = settings.mercy;
    selected = new Set();
    slotAssignedAuditoriums = new Map();
  }

  async function loadPagePlan(target: Page) {
    const kind = planKindFor(target);
    if (!kind || !$account?.departmentId || !$account?.token) return;
    const departmentId = $account.departmentId;
    const userId = $account.user.id;
    activePlan = null;
    pendingPlanRestore = null;
    draftHydrated = false;
    planSaveState = 'loading';
    planSaveMessage = '';
    try {
      const plans = await planningRequest(`?department_id=${encodeURIComponent(departmentId)}`) as any[];
      if (page !== target || $account?.user.id !== userId || $account.departmentId !== departmentId) return;
      let plan = plans.find((item) => item.kind === kind && item.status === 'draft' && item.owner_id === userId);
      if (!plan) plan = await planningRequest('', 'POST', { department_id: departmentId, kind, title: sections.find((item) => item.page === target)?.name ?? '' });
      const detail = await planningRequest(`/${plan.id}`) as PlanDraft;
      if (page !== target || $account?.user.id !== userId || $account.departmentId !== departmentId) return;
      activePlan = detail;
      if (detail.settings && Object.keys(detail.settings).length) {
        restorePlanSettings(detail.settings);
        pendingPlanRestore = detail.slots ?? [];
      }
      const ready = target === 'meetings'
        ? meetingTeachers.length > 0
        : !!teacher && groups.length > 0 &&
          (target !== 'retakes' || retakeMode !== 'commission' || (commissionChoice === 'people' ? commissionTeachers.length > 0 : !!commissionGroupId));
      if (ready && start && finish && start <= finish) {
        await generate();
      } else {
        pendingPlanRestore = null;
        draftHydrated = true;
      }
      planSaveState = 'saved';
      savedDraftSignature = '';
    } catch (cause) {
      draftHydrated = true;
      planSaveState = 'error';
      planSaveMessage = cause instanceof Error ? cause.message : 'Не удалось открыть сохранённый план.';
    }
  }

  function currentDraftSettings() {
    return {
      page, start, finish, teacher, groups, auditoriums,
      commissionTeachers, meetingTeachers, retakeMode, commissionChoice, commissionGroupId, mercy
    };
  }

  function currentDraftSlots() {
    return [...selected].flatMap((key) => {
      const split = key.lastIndexOf('-');
      const eventDate = key.slice(0, split);
      const slotNumber = Number(key.slice(split + 1));
      const slot = SLOTS.find((item) => item.number === slotNumber);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(eventDate) || !slot) return [];
      const resources: { kind: 'person' | 'group' | 'auditorium'; external_id: string; display_name: string }[] = [];
      const people = page === 'meetings' ? meetingTeachers : [teacher, ...(page === 'retakes' && retakeMode === 'commission' && commissionChoice === 'people' ? commissionTeachers : [])].filter((item): item is SearchItem => Boolean(item));
      for (const person of people) resources.push({ kind: 'person', external_id: person.id, display_name: person.label });
      if (page === 'retakes' && retakeMode === 'commission' && commissionChoice === 'group') {
        const group = COMMISSION_GROUPS.find((item) => item.id === commissionGroupId);
        for (const person of group?.people ?? []) resources.push({ kind: 'person', external_id: person.id, display_name: person.label });
      }
      if (page !== 'meetings') for (const group of groups) resources.push({ kind: 'group', external_id: group.id, display_name: group.label });
      const auditorium = slotAssignedAuditoriums.get(key);
      if (auditorium) resources.push({ kind: 'auditorium', external_id: auditorium.id, display_name: auditorium.name });
      const uniqueResources = [...new Map(resources.map((resource) => [`${resource.kind}:${resource.external_id}`, resource])).values()];
      return [{ event_date: eventDate, slot_number: slot.number, starts_at: `${slot.start}:00`, ends_at: `${slot.end}:00`, resources: uniqueResources }];
    });
  }

  function scheduleDraftSave() {
    if (draftSaveTimer !== null) window.clearTimeout(draftSaveTimer);
    draftSaveTimer = window.setTimeout(() => {
      draftSaveTimer = null;
      draftSaveChain = draftSaveChain.then(saveCurrentDraft).catch(() => undefined);
    }, 500);
  }

  async function saveCurrentDraft() {
    const plan = activePlan;
    const target = page;
    if (!plan || !draftHydrated || !isPlanningPage(target)) return;
    planSaveState = 'saving';
    planSaveMessage = '';
    const body = { version: plan.version, settings: currentDraftSettings(), slots: currentDraftSlots() };
    try {
      let result: { version: number };
      try {
        result = await planningRequest(`/${plan.id}/draft`, 'PUT', body) as { version: number };
      } catch (cause) {
        if ((cause as Error & { status?: number }).status !== 409) throw cause;
        const latest = await planningRequest(`/${plan.id}`) as PlanDraft;
        if (activePlan?.id !== plan.id || page !== target) return;
        body.version = latest.version;
        result = await planningRequest(`/${plan.id}/draft`, 'PUT', body) as { version: number };
      }
      if (activePlan?.id !== plan.id || page !== target) return;
      activePlan = { ...plan, version: result.version, settings: body.settings };
      planSaveState = 'saved';
      planSaveMessage = '';
    } catch (cause) {
      planSaveState = 'error';
      planSaveMessage = cause instanceof Error ? cause.message : 'Не удалось сохранить план.';
    }
  }

  $: draftSignature = isPlanningPage(page) ? JSON.stringify({ page, start, finish, teacher, groups, auditoriums, commissionTeachers, meetingTeachers, retakeMode, commissionChoice, commissionGroupId, mercy, selected: [...selected].sort(), assignments: [...slotAssignedAuditoriums.entries()] }) : '';
  $: if (draftHydrated && activePlan && isPlanningPage(page) && draftSignature !== savedDraftSignature) {
    savedDraftSignature = draftSignature;
    scheduleDraftSave();
  }

  function rebuildFromLoaded() {
    if (!loadedSchedule) return;
    const data = loadedSchedule;
    const result = buildWeeks(
      data.start,
      data.finish,
      data.teacherEvents,
      data.groupEvents,
      data.groups,
      data.candidates.length ? { people: data.candidates, events: data.commissionEvents, failedIds: data.failedIds, mercy: data.mode === 'meeting' ? false : mercy } : undefined,
      data.mode,
      selected,
      data.auditoriumEvents,
      data.auditoriums
    );
    weeks = result.weeks;
    unknownDates = result.unknownDates;
  }

  async function ensureBuildings() {
    loadingBuildings = true;
    try {
      const fetched = await getBuildings();
      if (fetched && fetched.length > 0) {
        availableBuildings = fetched;
      }
      if (!modalBuildingOid && availableBuildings.length > 0) {
        const ulk6 = availableBuildings.find((b) => b.name.includes('УЛК-6') || b.buildingOid === 16);
        modalBuildingOid = ulk6 ? ulk6.buildingOid : availableBuildings[0].buildingOid;
      }
    } catch (e) {
      console.error('Failed to load buildings', e);
    } finally {
      loadingBuildings = false;
    }
  }

  onMount(() => {
    const activation = new URLSearchParams(location.hash.slice(1)).get('activation');
    if (activation) { setAccount(null); activationToken = activation; page = 'admin'; history.replaceState(null, '', location.pathname + location.search); }
    else void restoreAccount();
    ensureBuildings();
    const updateCurrentDate = () => { currentDateIso = toIso(new Date()); };
    const currentDateTimer = window.setInterval(() => { updateCurrentDate(); void restoreAccount(); }, 60_000);
    const handleScroll = () => {
      hideTooltip();
      hideViewerTooltip();
    };
    window.addEventListener('scroll', handleScroll, { capture: true, passive: true });
    return () => {
      window.clearInterval(currentDateTimer);
      window.removeEventListener('scroll', handleScroll, true);
      if (generateTimer !== null) window.clearTimeout(generateTimer);
      if (viewerLoadTimer !== null) window.clearTimeout(viewerLoadTimer);
      viewerRequestId++;
    };
  });

  async function onSidebarBuildingChange() {
    if (!selectedBuildingOid) {
      buildingAuditoriums = [];
      return;
    }
    loadingBuildingAuds = true;
    try {
      buildingAuditoriums = await getAuditoriums(selectedBuildingOid);
    } catch (e) {
      console.error('Failed to load building auditoriums', e);
    } finally {
      loadingBuildingAuds = false;
    }
  }

  function toggleSidebarAudType(typeId: string) {
    const next = new Set(selectedAudTypes);
    if (next.has(typeId)) next.delete(typeId); else next.add(typeId);
    selectedAudTypes = next;
  }

  async function addAuditorium(item: SearchItem) {
    if (auditoriums.some((a) => a.id === item.id)) return;
    auditoriums = [...auditoriums, item];
    if (hasGenerated && loadedSchedule) {
      try {
        const events = await getSchedule('auditorium', item.id, loadedSchedule.start, loadedSchedule.finish);
        if (!loadedSchedule) return;
        loadedSchedule.auditoriumEvents.set(item.id, events);
        loadedSchedule.auditoriums = auditoriums;
        rebuildFromLoaded();
      } catch (e) {
        console.error('Failed to load auditorium schedule', e);
      }
    } else queueGenerate();
  }

  function addAuditoriumFromItem(item: AuditoriumItem) {
    const label = item.name ? `${item.name} (${item.building})` : `${item.number} (${item.building})`;
    addAuditorium({
      id: String(item.auditoriumOid),
      label,
      description: `${item.typeOfAuditorium || 'Аудитория'}, ${item.amount || 0} мест`,
      type: 'auditorium'
    });
  }

  function removeAuditorium(id: string) {
    auditoriums = auditoriums.filter((a) => a.id !== id);
    if (loadedSchedule) {
      loadedSchedule.auditoriumEvents.delete(id);
      loadedSchedule.auditoriums = auditoriums;
      rebuildFromLoaded();
    }
  }

  async function openAuditoriumModal(targetSlotKey: string = 'all') {
    modalTargetSlotKey = targetSlotKey;
    await ensureBuildings();
    showAudModal = true;
    modalError = '';
    modalSearchQuery = '';
    modalMinCapacity = 0;
    if (selectedBuildingOid) {
      modalBuildingOid = selectedBuildingOid;
    } else if (!modalBuildingOid && availableBuildings.length > 0) {
      const ulk6 = availableBuildings.find((b) => b.name.includes('УЛК-6') || b.buildingOid === 16);
      modalBuildingOid = ulk6 ? ulk6.buildingOid : availableBuildings[0].buildingOid;
    }
    modalAudTypes = new Set(selectedAudTypes);
    await loadModalBuildingData();
  }

  function closeAuditoriumModal() {
    showAudModal = false;
  }

  function openSelectedSlotsModal() {
    if (selectedCount > 0) {
      showSelectedModal = true;
    }
  }

  function closeSelectedSlotsModal() {
    showSelectedModal = false;
  }

  function removeSelectedSlot(key: string) {
    const next = new Set(selected);
    next.delete(key);
    selected = next;
    slotAssignedAuditoriums.delete(key);
    slotAssignedAuditoriums = new Map(slotAssignedAuditoriums);
    rebuildFromLoaded();
    if (selected.size === 0) {
      closeSelectedSlotsModal();
    }
  }

  function findAuditoriumForSlot(slotKey: string) {
    closeSelectedSlotsModal();
    openAuditoriumModal(slotKey);
  }

  async function loadModalBuildingData() {
    if (!modalBuildingOid || !selectedDetails.length) return;
    modalLoading = true;
    modalError = '';
    try {
      const dates = selectedDetails.map((d) => d.cell.date).sort();
      const minDate = dates[0];
      const maxDate = dates[dates.length - 1];
      const [auds, events] = await Promise.all([
        getAuditoriums(modalBuildingOid),
        getBuildingSchedule(modalBuildingOid, minDate, maxDate)
      ]);
      modalAuditoriumsList = auds;
      modalBuildingSchedule = events;
      updateModalAvailability();
    } catch (e) {
      modalError = e instanceof Error ? e.message : 'Не удалось загрузить данные по аудиториям корпуса.';
    } finally {
      modalLoading = false;
    }
  }

  function updateModalAvailability() {
    if (!modalAuditoriumsList.length) {
      modalAvailability = [];
      return;
    }
    const slotsToCheck = (modalTargetSlotKey === 'all')
      ? selectedDetails.map((d) => ({ date: d.cell.date, slot: d.slot }))
      : selectedDetails.filter((d) => d.cell.key === modalTargetSlotKey).map((d) => ({ date: d.cell.date, slot: d.slot }));

    modalAvailability = checkAuditoriumsAvailability(
      modalAuditoriumsList,
      modalBuildingSchedule,
      slotsToCheck.length ? slotsToCheck : selectedDetails.map((d) => ({ date: d.cell.date, slot: d.slot }))
    );
  }

  function toggleModalAudType(typeId: string) {
    const next = new Set(modalAudTypes);
    if (next.has(typeId)) next.delete(typeId); else next.add(typeId);
    modalAudTypes = next;
  }

  function pickAuditoriumFromModal(item: AuditoriumItem) {
    const assigned: AssignedAuditorium = {
      id: String(item.auditoriumOid),
      name: item.name || item.number,
      number: item.number,
      building: item.building,
      capacity: item.capacity,
      type: item.typeOfAuditorium
    };

    if (modalTargetSlotKey === 'all') {
      for (const key of selected) {
        slotAssignedAuditoriums.set(key, assigned);
      }
      slotAssignedAuditoriums = new Map(slotAssignedAuditoriums);
      addAuditoriumFromItem(item);
      showToast(`Аудитория ${assigned.name} назначена на все выбранные пары`);
    } else {
      slotAssignedAuditoriums.set(modalTargetSlotKey, assigned);
      slotAssignedAuditoriums = new Map(slotAssignedAuditoriums);
      addAuditoriumFromItem(item);
      showToast(`Аудитория ${assigned.name} назначена на пару`);
    }

    closeAuditoriumModal();
    if (selected.size > 0) {
      showSelectedModal = true;
    }
  }

  function chooseTeacher(item: SearchItem) { invalidate(); committeeError = ''; teacher = item; commissionTeachers = commissionTeachers.filter((person) => person.id !== item.id); queueGenerate(); }
  function removeTeacher() { invalidate(); committeeError = ''; teacher = null; }
  function changeRetakeMode(mode: 'first' | 'commission') { if (retakeMode !== mode) { invalidate(); retakeMode = mode; committeeError = ''; queueGenerate(); } }
  function changeCommissionChoice(choice: 'people' | 'group') { if (commissionChoice !== choice) { invalidate(); commissionChoice = choice; committeeError = ''; queueGenerate(); } }
  function changeCommissionGroup(id: string) { invalidate(); commissionGroupId = id; queueGenerate(); }
  function changeMercy(value: boolean) { mercy = value; rebuildFromLoaded(); }
  function commissionCandidates(): SearchItem[] {
    if (page !== 'substitutions' && (page !== 'retakes' || retakeMode !== 'commission')) return [];
    const people = commissionChoice === 'people' ? commissionTeachers : selectedCommissionGroup?.people ?? [];
    return people.filter((person) => person.id !== teacher?.id);
  }
  function addCommissionTeacher(item: SearchItem) {
    if (item.id === teacher?.id) { committeeError = 'Основной преподаватель уже выбран.'; return; }
    if (commissionTeachers.some((person) => person.id === item.id)) { committeeError = 'Этот преподаватель уже добавлен.'; return; }
    if (page === 'retakes' && commissionTeachers.length >= 2) return;
    invalidate();
    committeeError = '';
    commissionTeachers = [...commissionTeachers, item];
    queueGenerate();
  }
  function removeCommissionTeacher(id: string) { invalidate(); committeeError = ''; commissionTeachers = commissionTeachers.filter((person) => person.id !== id); queueGenerate(); }
  function addMeetingTeacher(item: SearchItem) {
    if (meetingTeachers.some((person) => person.id === item.id)) { meetingError = 'Этот преподаватель уже добавлен.'; return; }
    invalidate();
    meetingError = '';
    meetingTeachers = [...meetingTeachers, item];
    queueGenerate();
  }
  function removeMeetingTeacher(id: string) { invalidate(); meetingError = ''; meetingTeachers = meetingTeachers.filter((person) => person.id !== id); queueGenerate(); }
  function addGroup(item: SearchItem) {
    if (groups.some((group) => group.id === item.id)) return;
    invalidate();
    groups = [...groups, item];
    queueGenerate();
  }
  function removeGroup(id: string) { invalidate(); groups = groups.filter((group) => group.id !== id); queueGenerate(); }
  function changeStart(value: string) { invalidate(); start = value; queueGenerate(); }
  function changeFinish(value: string) { invalidate(); finish = value; queueGenerate(); }

  async function loadCommissionSchedules(candidates: SearchItem[], signal: AbortSignal) {
    const events = new Map<string, Awaited<ReturnType<typeof getSchedule>>>();
    const failedIds = new Set<string>();
    for (let offset = 0; offset < candidates.length; offset += 4) {
      const batch = candidates.slice(offset, offset + 4);
      const results = await Promise.allSettled(batch.map((person) => getSchedule('person', person.id, start, finish, signal)));
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') events.set(batch[index].id, result.value);
        else failedIds.add(batch[index].id);
      });
    }
    return { events, failedIds };
  }

  async function generate() {
    const isMeeting = page === 'meetings';
    const candidates = isMeeting ? meetingTeachers : commissionCandidates();
    if ((!isMeeting && !teacher) || (!isMeeting && page !== 'substitutions' && !groups.length) || !start || !finish || start > finish || ((isMeeting || page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && !candidates.length)) return;
    const restoreSlots = pendingPlanRestore;
    const wasDraftHydrated = draftHydrated;
    invalidate();
    pendingPlanRestore = restoreSlots;
    draftHydrated = wasDraftHydrated;
    const current = ++requestNumber;
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    try {
      const [teacherSchedule, commissionSchedules, groupSchedules, audSchedules] = await Promise.all([
        isMeeting ? Promise.resolve([] as ApiItem[]) : getSchedule('person', teacher!.id, start, finish, controller.signal),
        loadCommissionSchedules(candidates, controller.signal),
        Promise.all((isMeeting || page === 'substitutions' ? [] : groups).map((group) => getSchedule('group', group.id, start, finish, controller.signal))),
        Promise.all(auditoriums.map((aud) => getSchedule('auditorium', aud.id, start, finish, controller.signal)))
      ]);
      if (current !== requestNumber) return;
      const activeGroups = isMeeting || page === 'substitutions' ? [] : groups;
      const groupEvents = new Map<string, ApiItem[]>(activeGroups.map((group, i) => [group.id, groupSchedules[i]]));
      const auditoriumEvents = new Map<string, ApiItem[]>(auditoriums.map((aud, i) => [aud.id, audSchedules[i]]));
      loadedSchedule = {
        start,
        finish,
        teacherEvents: teacherSchedule,
        groupEvents,
        groups: activeGroups,
        candidates,
        commissionEvents: commissionSchedules.events,
        failedIds: commissionSchedules.failedIds,
        mode: isMeeting ? 'meeting' : page === 'substitutions' ? 'substitution' : 'availability',
        auditoriumEvents,
        auditoriums
      };
      rebuildFromLoaded();
      if (pendingPlanRestore) {
        const restored = new Set<string>();
        const assigned = new Map<string, AssignedAuditorium>();
        for (const saved of pendingPlanRestore) {
          const date = String(saved.event_date).slice(0, 10);
          const number = Number(saved.slot_number);
          const key = `${date}-${number}`;
          if (weeks.some((week) => week.rows.some((row) => row.slot.number === number && row.cells.some((cell) => cell.key === key)))) restored.add(key);
          const auditorium = (saved.resources ?? []).find((resource: any) => resource.kind === 'auditorium');
          if (auditorium) assigned.set(key, { id: String(auditorium.external_id), name: String(auditorium.display_name || auditorium.external_id) });
        }
        selected = restored;
        slotAssignedAuditoriums = assigned;
        pendingPlanRestore = null;
        rebuildFromLoaded();
        draftHydrated = true;
      } else if (activePlan && isPlanningPage(page)) draftHydrated = true;
      failedCommissionCount = commissionSchedules.failedIds.size;
      hasGenerated = true;
    } catch (cause) {
      if (current === requestNumber && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        error = cause instanceof Error ? cause.message : 'Не удалось загрузить расписание.';
        if (!pendingPlanRestore && activePlan && isPlanningPage(page)) draftHydrated = true;
      }
    } finally {
      if (current === requestNumber) loading = false;
    }
  }

  function queueGenerate(delay = 250) {
    if (generateTimer !== null) window.clearTimeout(generateTimer);
    generateTimer = window.setTimeout(() => {
      generateTimer = null;
      const isMeeting = page === 'meetings';
      const candidates = isMeeting ? meetingTeachers : commissionCandidates();
      const needsCandidates = isMeeting || page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission');
      if ((isMeeting ? meetingTeachers.length > 0 : !!teacher) &&
          (isMeeting || page === 'substitutions' || groups.length > 0) &&
          (!needsCandidates || candidates.length > 0) && start && finish && start <= finish) {
        void generate();
      }
    }, delay);
  }

  function toggle(cell: Cell) {
    if (!cell.available) return;
    const next = new Set(selected);
    if (next.has(cell.key)) {
      next.delete(cell.key);
      slotAssignedAuditoriums.delete(cell.key);
      slotAssignedAuditoriums = new Map(slotAssignedAuditoriums);
    } else {
      next.add(cell.key);
    }
    selected = next;
    rebuildFromLoaded();
    if (activeTooltip) {
      for (const w of weeks) {
        for (const r of w.rows) {
          const found = r.cells.find((c) => c.key === activeTooltip.cell.key);
          if (found) {
            activeTooltip = { ...activeTooltip, cell: found };
            break;
          }
        }
      }
    }
  }

  function clearSelection() {
    selected = new Set();
    rebuildFromLoaded();
    hideTooltip();
    showSelectedModal = false;
  }

  async function go(next: Page) {
    if (['retakes', 'consultations', 'substitutions', 'meetings'].includes(next) && !canPlan) {
      invalidate(); activePlan = null; draftHydrated = false; page = 'admin';
      window.scrollTo({ top: 0, behavior: 'smooth' }); return;
    }
    if (next !== page && isPlanningPage(page) && activePlan) {
      if (draftSaveTimer !== null) { window.clearTimeout(draftSaveTimer); draftSaveTimer = null; }
      await draftSaveChain;
      await saveCurrentDraft();
    }
    if (next !== page) { invalidate(); auditoriums = []; }
    activePlan = null; pendingPlanRestore = null; draftHydrated = false; planSaveState = 'idle'; planSaveMessage = '';
    if (next === 'retakes' && commissionTeachers.length > 2) commissionTeachers = commissionTeachers.slice(0, 2);
    page = next;
    if (isPlanningPage(next)) void loadPagePlan(next);
    if (next === 'schedule') void loadViewerDepartmentGroups().then(generateScheduleView);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function dateShort(value: string) { return formatDate(value, { day: '2-digit', month: '2-digit' }); }
  function freeCommission(cell: Cell) { return cell.commission.filter((entry) => entry.available).map((entry) => entry.person.label); }
  function commissionReason(reason: 'free' | 'busy' | 'no-lessons' | 'load-error') { return reason === 'free' ? (page === 'substitutions' ? 'может заменить' : 'может присутствовать') : reason === 'busy' ? 'занят в это время' : reason === 'no-lessons' ? 'нет пар в этот день' : 'расписание не загрузилось'; }
  function windowStatusShort(status: WindowStatus, windowPairs = 0) {
    return status === 'none' ? 'Без окон' : `Окно (${formatPairCount(windowPairs)})`;
  }
  function cellHasNoLessonsToday(cell: Cell) {
    if (page === 'meetings') {
      return !!cell.teachersDetails?.length && cell.teachersDetails.every((person) => person.noLessons);
    }
    const hasTeacher = Boolean(teacher);
    const teacherHasNoLessons = !hasTeacher || cell.teacherNoLessonsToday;
    const groupsHaveNoLessons = !groups.length || (cell.groupsDetails.length > 0 && cell.groupsDetails.every((group) => group.noLessonsToday));
    return (hasTeacher || groups.length > 0) && teacherHasNoLessons && groupsHaveNoLessons;
  }
  function windowStatusFull(cell: Cell) {
    if (page === 'meetings') {
      const teachersWithWindow = cell.teachersDetails?.filter((t) => t.hasWindow).map((t) => `${t.person.label} (${formatPairCount(t.windowPairs)})`) ?? [];
      if (teachersWithWindow.length === 0) return 'без окон';
      if (teachersWithWindow.length === (cell.teachersDetails?.length ?? 0)) return `окно у всех преподавателей: ${teachersWithWindow.join(', ')}`;
      return `окно у: ${teachersWithWindow.join(', ')}`;
    }
    const groupsWithWindow = cell.groupsDetails.filter((group) => !group.busy && group.hasWindow).map((group) => `${group.group.label} (${formatPairCount(group.windowPairs)})`);
    const teacherWindow = cell.teacherHasWindow ? `преподавателя (${formatPairCount(cell.teacherWindowPairs)})` : '';
    if (cell.windowStatus === 'group-window') {
      return groupsWithWindow.length ? `окно у ${groupsWithWindow.join(', ')}` : `окно у групп (${formatPairCount(cell.windowPairs)})`;
    }
    if (cell.windowStatus === 'teacher-window') return `окно у ${teacherWindow}`;
    if (cell.windowStatus === 'both-window') {
      return `окно у ${[teacherWindow, ...groupsWithWindow].filter(Boolean).join(', ')}`;
    }
    return 'без окон';
  }
  type DisplayMode = 'windows' | 'classic';
  const DISPLAY_MODE_STORAGE_KEY = 'zapara_display_mode';
  let displayMode: DisplayMode = 'windows';

  if (typeof window !== 'undefined') {
    const savedMode = localStorage.getItem(DISPLAY_MODE_STORAGE_KEY);
    if (savedMode === 'windows' || savedMode === 'classic') {
      displayMode = savedMode;
    }
  }

  function setDisplayMode(mode: DisplayMode) {
    displayMode = mode;
    if (typeof window !== 'undefined') {
      localStorage.setItem(DISPLAY_MODE_STORAGE_KEY, mode);
    }
    if (mode === 'classic') {
      hideTooltip();
    }
  }

  function cellAriaLabel(cell: Cell, slot: { start: string; end: string }): string {
    if (displayMode === 'classic') {
      if (cell.outOfRange) return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, вне периода`;
      if (!cell.available) return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, ${page === 'substitutions' ? 'нет занятия' : page === 'meetings' ? 'не все преподаватели свободны' : cell.teacherBusy ? 'преподаватель занят' : 'все группы заняты'}`;
      if (page === 'meetings') return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, свободно, все преподаватели свободны`;
      if (page === 'substitutions') return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, занятие: ${cell.lessons.join(', ')}`;
      return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, свободно: ${cell.freeGroups.map((group) => group.label).join(', ')}`;
    }
    if (cell.outOfRange) return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, вне периода`;
    if (!cell.available) return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, ${cell.unavailableText ?? 'занято'}`;
    if (page === 'meetings') return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, свободно, все преподаватели свободны (${windowStatusFull(cell)})`;
    if (page === 'substitutions') return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, занятие: ${cell.lessons.join(', ')}`;
    return `${formatDate(cell.date)}, ${slot.start}–${slot.end}, свободно (${windowStatusFull(cell)}), свободны: ${cell.freeGroups.map((group) => group.label).join(', ')}`;
  }
  function cellTitle(cell: Cell): string {
    if (displayMode === 'classic') return '';
    if (cell.outOfRange) return 'Вне периода';
    if (!cell.available) {
      const details: string[] = [];
      if (cell.lessons.length) details.push(`преп.: ${cell.lessons.join('; ')}`);
      if (cell.busyGroups?.length) details.push(`заняты: ${cell.busyGroups.map((g) => g.label).join(', ')}`);
      if (cell.busyAuditoriums?.length) details.push(`заняты ауд.: ${cell.busyAuditoriums.map((a) => a.label).join(', ')}`);
      return details.length ? `${cell.unavailableText ?? 'Занято'} (${details.join(' | ')})` : (cell.unavailableText ?? 'Занято');
    }
    if (page === 'substitutions') return cell.lessons.join('; ');
    if (page === 'meetings') return `Все преподаватели свободны (${windowStatusFull(cell)})`;
    return `Свободно: ${cell.freeGroups.map((g) => g.label).join(', ')} (${windowStatusFull(cell)})`;
  }

  type ActiveTooltip = {
    cell: Cell;
    slot: Slot;
    targetRect: DOMRect;
  };

  let activeTooltip: ActiveTooltip | null = null;

  function showTooltip(cell: Cell, slot: Slot, event: MouseEvent | FocusEvent) {
    if (displayMode === 'classic') return;
    const target = event.currentTarget as HTMLElement | null;
    if (!target) return;
    const targetRect = target.getBoundingClientRect();
    activeTooltip = { cell, slot, targetRect };
  }

  function hideTooltip() {
    activeTooltip = null;
  }

  function fitTooltip(node: HTMLElement, targetRect: DOMRect | null) {
    let ro: ResizeObserver | null = null;

    function position(rect: DOMRect | null) {
      if (!rect) return;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const pad = 12;
      const gap = 8;

      const maxW = Math.min(390, Math.max(200, vw - pad * 2));
      node.style.maxWidth = `${maxW}px`;
      node.style.maxHeight = 'none';
      node.style.overflowY = 'visible';

      const tooltipWidth = node.offsetWidth;
      let tooltipHeight = node.offsetHeight;

      const targetCenterX = rect.left + rect.width / 2;
      const idealLeft = targetCenterX - tooltipWidth / 2;
      const left = Math.max(pad, Math.min(vw - pad - tooltipWidth, idealLeft));

      const spaceAbove = rect.top - pad - gap;
      const spaceBelow = vh - rect.bottom - pad - gap;

      let top: number;
      let placement: 'top' | 'bottom';

      if (spaceAbove >= tooltipHeight) {
        placement = 'top';
        top = rect.top - gap - tooltipHeight;
      } else if (spaceBelow >= tooltipHeight) {
        placement = 'bottom';
        top = rect.bottom + gap;
      } else if (spaceAbove >= spaceBelow) {
        placement = 'top';
        const availableHeight = Math.max(100, spaceAbove);
        node.style.maxHeight = `${availableHeight}px`;
        node.style.overflowY = 'auto';
        top = rect.top - gap - node.offsetHeight;
      } else {
        placement = 'bottom';
        const availableHeight = Math.max(100, spaceBelow);
        node.style.maxHeight = `${availableHeight}px`;
        node.style.overflowY = 'auto';
        top = rect.bottom + gap;
      }

      const finalTop = Math.max(pad, Math.min(vh - pad - node.offsetHeight, top));
      const finalLeft = Math.max(pad, Math.min(vw - pad - node.offsetWidth, left));

      node.style.left = `${Math.round(finalLeft)}px`;
      node.style.top = `${Math.round(finalTop)}px`;
      node.classList.toggle('tooltip-top', placement === 'top');
      node.classList.toggle('tooltip-bottom', placement === 'bottom');
    }

    position(targetRect);

    const onResize = () => position(targetRect);
    window.addEventListener('resize', onResize);

    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => position(targetRect));
      ro.observe(node);
    }

    return {
      update(newRect: DOMRect | null) {
        targetRect = newRect;
        position(targetRect);
      },
      destroy() {
        window.removeEventListener('resize', onResize);
        ro?.disconnect();
      }
    };
  }
</script>

<svelte:window on:scroll={() => { hideTooltip(); hideViewerTooltip(); }} />

<svelte:head>
  <title>{page === 'home' ? 'Запара — планирование для преподавателей' : page === 'consultations' ? 'Консультации — Запара' : page === 'admin' ? 'Аккаунты — Запара' : `${sections.find((section) => section.page === page)?.name} — Запара`}</title>
</svelte:head>

<div class="site-shell">
  <header class="topbar">
    <button class="brand" type="button" on:click={() => go('home')} aria-label="На главную">
      <span class="brand-mark"><span></span><span></span><span></span><span></span></span>
      <span class="brand-copy"><strong>Запара</strong><small>планирование времени</small></span>
    </button>
    <nav aria-label="Основная навигация">
      <button type="button" class:nav-current={page === 'home'} on:click={() => go('home')}>Главная</button>
      <button type="button" class:nav-current={page === 'schedule'} on:click={() => go('schedule')}>Группы</button>
      <button type="button" class:nav-current={page === 'teachers'} on:click={() => go('teachers')}>Преподаватели</button>
      <button type="button" class:nav-current={page === 'auditoriums'} on:click={() => go('auditoriums')}>Аудитории</button>
      {#if canPlan}
        <button type="button" class:nav-current={page === 'consultations'} on:click={() => go('consultations')}>Консультации</button>
        <button type="button" class:nav-current={page === 'retakes'} on:click={() => go('retakes')}>Пересдачи</button>
        <button type="button" class:nav-current={page === 'substitutions'} on:click={() => go('substitutions')}>Замены</button>
        <button type="button" class:nav-current={page === 'meetings'} on:click={() => go('meetings')}>Встречи</button>
      {/if}
    </nav>
    <button type="button" class="account-entry" class:account-entry-active={page === 'admin'} on:click={() => go('admin')}><span class="account-entry-icon" aria-hidden="true">{#if $account}{$account.user.display_name.trim().slice(0, 1).toUpperCase()}{:else}<AppIcon name="teacher" size={17} />{/if}</span><span class="account-entry-label">{$accountChecking ? 'Проверяем вход' : $account ? $account.user.display_name : 'Войти'}</span>{#if $account && $unreadNotifications}<span class="account-unread" aria-label={`Непрочитанных уведомлений: ${$unreadNotifications}`}>{$unreadNotifications}</span>{/if}</button>
  </header>

  <main>
    {#if canPlan && ['retakes', 'consultations', 'substitutions', 'meetings'].includes(page)}
      <div class="planning-save-note" role="note"><AppIcon name="info" size={18} /><span>{page === 'substitutions' ? 'Выбранные замены сохраняются в базе кафедры и доступны планировщикам.' : 'Черновик автоматически сохраняется в вашем аккаунте и восстановится при следующем входе.'}</span></div>
    {/if}
    {#if page === 'home'}
      <div class="home-workspace">
        <h1 class="home-title">Разделы</h1>
        <div class="home-dashboard">
          <div class="home-sections">
            <section class="home-section" aria-labelledby="home-schedule-title">
              <div class="home-section-head"><div><h2 id="home-schedule-title">Расписание</h2><p>Просмотр расписания ОмГТУ без входа.</p></div></div>
              <div class="home-links home-links-schedule">{#each sections.filter((item) => item.guest) as section}<button type="button" class="home-link" on:click={() => go(section.page)}><span class="home-link-icon"><AppIcon name={section.icon} size={24} /></span><span class="home-link-text"><strong>{section.name}</strong><small>{section.description}</small><em>Открыто для всех</em></span><span class="home-link-arrow"><AppIcon name="arrow" size={19} /></span></button>{/each}</div>
            </section>
            <section class="home-section" aria-labelledby="home-planning-title">
              <div class="home-section-head"><div><h2 id="home-planning-title">Планирование</h2><p>Инструменты для работы кафедры.</p></div></div>
              <div class="home-links home-links-planning">{#each sections.filter((item) => !item.guest) as section}<button type="button" class="home-link" class:home-link-locked={!canPlan} on:click={() => canPlan ? go(section.page) : go('admin')}><span class="home-link-icon"><AppIcon name={section.icon} size={22} /></span><span class="home-link-text"><strong>{section.name}</strong><small>{section.description}</small><em>{canPlan ? 'Открыть раздел' : 'Войдите, чтобы открыть'}</em></span><span class="home-link-arrow">{#if canPlan}<AppIcon name="arrow" size={18} />{:else}<AppIcon name="lock" size={17} />{/if}</span></button>{/each}</div>
            </section>
          </div>
          <aside class="home-account-card" aria-labelledby="home-account-title">
            <AppIcon name="teacher" size={26} />
            {#if !$account}<h2 id="home-account-title">Аккаунт кафедры</h2><p>Войдите, чтобы планировать консультации, пересдачи, замены и встречи.</p><button type="button" class="primary-button" on:click={() => go('admin')}>Войти в аккаунт <AppIcon name="arrow-up-right" size={17} /></button><small>Нет доступа? Обратитесь к администратору кафедры.</small>
            {:else}<h2 id="home-account-title">{$account.user.display_name}</h2><p>{canPlan ? 'Ваше рабочее пространство кафедры готово.' : 'У вас доступ для просмотра. Для планирования обратитесь к администратору кафедры.'}</p><button type="button" class="primary-button" on:click={() => go('admin')}>Открыть аккаунт <AppIcon name="arrow-up-right" size={17} /></button>{/if}
          </aside>
        </div>
      </div>
    {:else if page === 'admin'}
        <Admin {activationToken} />
    {:else if page === 'teachers'}
        <TeacherSchedule on:home={() => go('home')} />
    {:else if page === 'auditoriums'}
        <AuditoriumSchedule on:home={() => go('home')} />
    {:else if page === 'substitutions'}
        <Substitutions on:home={() => go('home')} />
    {:else if page === 'consultations' || page === 'retakes' || page === 'meetings'}
      <div class="workspace">
        <h1 class="visually-hidden">{page === 'retakes' ? 'Пересдачи' : page === 'meetings' ? 'Рабочие встречи' : 'Консультации'}</h1>

        {#if page === 'retakes'}<div class="retake-mode"><div><span class="section-kicker">ФОРМАТ</span><strong>Тип пересдачи</strong></div><div class="retake-toggle" role="group" aria-label="Тип пересдачи"><button type="button" class:active={retakeMode === 'first'} aria-pressed={retakeMode === 'first'} on:click={() => changeRetakeMode('first')}>1 пересдача</button><button type="button" class:active={retakeMode === 'commission'} aria-pressed={retakeMode === 'commission'} on:click={() => changeRetakeMode('commission')}>Комиссионная пересдача</button></div></div>{/if}

        <div class="workspace-layout">
          <aside class="controls-panel">
            <div class="panel-top"><span class="panel-number">01 — НАСТРОЙКА</span><h2>{uiPage === 'substitutions' ? 'Кого и когда заменить?' : 'Кого и когда собрать?'}</h2></div>
            {#if page === 'meetings'}
              <div class="field-block"><div class="field-head"><label>Преподаватели</label><span>01</span></div>
                <SearchField type="person" placeholder="Добавить преподавателя" onPick={addMeetingTeacher} />
                {#if meetingTeachers.length}<div class="group-chips">{#each meetingTeachers as person (person.id)}<span class="group-chip">{person.label}<button type="button" on:click={() => removeMeetingTeacher(person.id)} aria-label={`Удалить преподавателя ${person.label}`}><AppIcon name="close" size={16} /></button></span>{/each}</div>{/if}
                {#if meetingError}<p class="form-error">{meetingError}</p>{:else}<p class="field-hint">Можно добавить любое количество преподавателей.</p>{/if}
              </div>
            {:else}<div class="field-block"><div class="field-head"><label>{uiPage === 'substitutions' ? 'Кого нужно заменить' : 'Преподаватель'}</label><span>01</span></div>
              {#if teacher}
                <div class="chosen-person"><span class="avatar">{teacher.label.slice(0, 1)}</span><span><strong>{teacher.label}</strong><small>Преподаватель выбран</small></span><button type="button" on:click={removeTeacher} aria-label="Удалить преподавателя"><AppIcon name="close" size={16} /></button></div>
              {:else}
                <SearchField type="person" placeholder="Начните вводить ФИО" onPick={chooseTeacher} />
                <p class="field-hint">Подсказки появятся после 4 символов</p>
              {/if}
            </div>{/if}

            {#if uiPage === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')}
              <div class="field-block"><div class="field-head"><label>{uiPage === 'substitutions' ? 'Кто может заменить' : 'Состав комиссии'}</label><span>02</span></div>
                <div class="commission-choice" role="group" aria-label={uiPage === 'substitutions' ? 'Способ выбора замещающих преподавателей' : 'Способ выбора комиссии'}><button type="button" class:active={commissionChoice === 'people'} aria-pressed={commissionChoice === 'people'} on:click={() => changeCommissionChoice('people')}>Конкретные люди</button><button type="button" class:active={commissionChoice === 'group'} aria-pressed={commissionChoice === 'group'} on:click={() => changeCommissionChoice('group')}>Тематическая группа</button></div>
                {#if commissionChoice === 'people'}
                  {#if uiPage === 'substitutions' || commissionTeachers.length < 2}<SearchField type="person" placeholder="Добавить преподавателя" onPick={addCommissionTeacher} />{/if}
                  {#if commissionTeachers.length}<div class="group-chips">{#each commissionTeachers as person (person.id)}<span class="group-chip">{person.label}<button type="button" on:click={() => removeCommissionTeacher(person.id)} aria-label={`Удалить преподавателя ${person.label}`}><AppIcon name="close" size={16} /></button></span>{/each}</div>{/if}
                  {#if committeeError}<p class="form-error">{committeeError}</p>{:else}<p class="field-hint">{uiPage === 'substitutions' ? 'Можно добавить любое количество преподавателей.' : 'Добавьте одного или двух преподавателей.'}</p>{/if}
                {:else}
                  <CustomSelect
                    ariaLabel="Тематическая группа преподавателей"
                    value={commissionGroupId}
                    placeholder="Выберите группу"
                    options={[
                      { value: '', label: 'Выберите группу' },
                      ...COMMISSION_GROUPS.map((group) => ({ value: group.id, label: group.label, extra: `${group.people.length}` }))
                    ]}
                    on:change={(event) => changeCommissionGroup(event.detail)}
                  />
                  {#if selectedCommissionGroup}<p class="field-hint">Кандидатов: {selectedCommissionGroup.people.filter((person) => person.id !== teacher?.id).length}. {uiPage === 'substitutions' ? 'Заменяемый преподаватель' : 'Основной преподаватель'} в число кандидатов не входит.</p>{/if}
                {/if}
              </div>
              <div class="mercy-field"><label class="mercy-switch"><input type="checkbox" checked={mercy} on:change={(event) => changeMercy((event.currentTarget as HTMLInputElement).checked)} /><span class="mercy-track"></span><strong>Милосердие</strong></label><p>Не считать доступными преподавателей, у которых в этот день совсем нет пар.</p></div>
            {/if}

            {#if uiPage !== 'substitutions' && page !== 'meetings'}<div class="field-block"><div class="field-head"><label>Учебные группы</label><span>{groupsStepNumber}</span></div>
              <SearchField type="group" placeholder="Например, М-251" onPick={addGroup} />
              {#if groups.length}<div class="group-chips">{#each groups as group (group.id)}<span class="group-chip">{group.label}<button type="button" on:click={() => removeGroup(group.id)} aria-label={`Удалить группу ${group.label}`}><AppIcon name="close" size={16} /></button></span>{/each}</div>{:else}<p class="field-hint">Можно добавить любое количество групп</p>{/if}
            </div>{/if}

            {#if uiPage !== 'substitutions' && page !== 'meetings'}
            <div class="field-block auditorium-field-block">
              <div class="field-head">
                <label>Аудитории <small class="field-optional">(опционально)</small></label>
                <span>{audStepNumber}</span>
              </div>
              <SearchField type="auditorium" placeholder="Номер или название, напр. 6-308" onPick={addAuditorium} />
              {#if auditoriums.length}
                <div class="group-chips">
                  {#each auditoriums as aud (aud.id)}
                    <span class="group-chip aud-chip">
                      {aud.label}
                      <button type="button" on:click={() => removeAuditorium(aud.id)} aria-label={`Удалить аудиторию ${aud.label}`}><AppIcon name="close" size={16} /></button>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="field-hint">Ограничивают выбор свободными слотами аудиторий</p>
              {/if}

              <div class="aud-filters-container">
                <button
                  type="button"
                  class="aud-filter-toggle"
                  class:open={showAudFilters}
                  on:click={() => {
                    showAudFilters = !showAudFilters;
                    if (showAudFilters) ensureBuildings();
                  }}
                >
                  <div class="filter-toggle-content">
                    <svg class="filter-toggle-lead-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
                    </svg>
                    <span class="filter-toggle-text">Фильтры по корпусу и типу</span>
                  </div>
                  <div class="filter-toggle-actions">
                    {#if selectedBuildingOid || selectedAudTypes.size > 0}
                      <span class="filter-count-badge">{(selectedBuildingOid ? 1 : 0) + (selectedAudTypes.size > 0 ? 1 : 0)}</span>
                    {/if}
                    <svg class="filter-toggle-chevron" width="12" height="8" viewBox="0 0 12 8" fill="none">
                      <path d="M1.5 2L6 6.5L10.5 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                </button>

                {#if showAudFilters}
                  <div class="aud-filter-panel">
                    <div class="aud-filter-row">
                      <label for="sidebar-building-select">Корпус:</label>
                      <CustomSelect
                        id="sidebar-building-select"
                        ariaLabel="Корпус"
                        bind:value={selectedBuildingOid}
                        placeholder="Все корпуса"
                        loading={loadingBuildings}
                        options={[
                          { value: null, label: 'Все корпуса' },
                          ...availableBuildings.map((b) => ({ value: b.buildingOid, label: b.name }))
                        ]}
                        on:change={(e) => {
                          selectedBuildingOid = e.detail;
                          onSidebarBuildingChange();
                        }}
                      />
                    </div>

                    {#if groups.length > 1}
                      <div class="aud-filter-row">
                        <label for="sidebar-group-filter">Группа:</label>
                        <CustomSelect
                          id="sidebar-group-filter"
                          ariaLabel="Группа"
                          bind:value={selectedGroupFilter}
                          placeholder="Все группы"
                          options={[
                            { value: 'all', label: 'Все группы' },
                            ...groups.map((g) => ({ value: g.id, label: g.label }))
                          ]}
                        />
                      </div>
                    {/if}

                    <div class="aud-filter-types-block">
                      <span class="filter-types-title">Тип аудитории:</span>
                      <div class="aud-type-checkboxes">
                        {#each AUDITORIUM_TYPE_CATEGORIES as cat (cat.id)}
                          <label class="type-check-label">
                            <input
                              type="checkbox"
                              checked={selectedAudTypes.has(cat.id)}
                              on:change={() => toggleSidebarAudType(cat.id)}
                            />
                            <span>{cat.label}</span>
                          </label>
                        {/each}
                      </div>
                    </div>

                    {#if selectedBuildingOid}
                      <div class="quick-aud-section">
                        <div class="quick-aud-head">
                          <span>Аудитории корпуса ({filteredBuildingAuds.length}):</span>
                          {#if loadingBuildingAuds}
                            <span class="search-spinner"></span>
                          {/if}
                        </div>
                        {#if filteredBuildingAuds.length}
                          <div class="quick-aud-chips">
                            {#each filteredBuildingAuds.slice(0, 18) as aud (aud.auditoriumOid)}
                              {@const isAdded = auditoriums.some((a) => a.id === String(aud.auditoriumOid))}
                              <button
                                type="button"
                                class="quick-aud-chip"
                                class:added={isAdded}
                                on:click={() => isAdded ? removeAuditorium(String(aud.auditoriumOid)) : addAuditoriumFromItem(aud)}
                              >
                                <AppIcon name={isAdded ? 'check' : 'plus'} size={14} /> {aud.name || aud.number}
                                {#if aud.amount}<small>{aud.amount}м</small>{/if}
                              </button>
                            {/each}
                            {#if filteredBuildingAuds.length > 18}
                              <span class="quick-aud-more">и ещё {filteredBuildingAuds.length - 18}…</span>
                            {/if}
                          </div>
                        {:else if !loadingBuildingAuds}
                          <p class="quick-aud-empty">Нет аудиторий выбранного типа</p>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/if}
              </div>
            </div>
            {/if}

            <div class="field-block date-block"><div class="field-head"><label>Период</label><span>{periodStepNumber}</span></div><div class="date-fields"><div><label for="start-date">С</label><input id="start-date" type="date" value={start} on:change={(event) => changeStart((event.currentTarget as HTMLInputElement).value)} /></div><div><label for="end-date">ПО</label><input id="end-date" type="date" min={start} value={finish} on:change={(event) => changeFinish((event.currentTarget as HTMLInputElement).value)} /></div></div></div>
            {#if start && finish && start > finish}<p class="form-error">Дата окончания раньше даты начала.</p>{/if}
            <button class="primary-button generate-button" type="button" disabled={(page === 'meetings' ? !meetingTeachers.length : !teacher) || (page !== 'meetings' && uiPage !== 'substitutions' && !groups.length) || !start || !finish || start > finish || loading || ((uiPage === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && (commissionChoice === 'people' ? !commissionTeachers.length : !commissionGroupId))} on:click={generate}>{loading ? 'Загружаем расписание…' : uiPage === 'substitutions' ? 'Показать замены' : 'Показать свободное время'}<AppIcon name="arrow-up-right" size={18} /></button>
            <div class="panel-note"><AppIcon name="info" size={18} /><p>{uiPage === 'substitutions' ? 'Выбирайте занятия заменяемого преподавателя. Доступность коллег показана под каждой парой и не ограничивает выбор.' : page === 'meetings' ? 'Зелёные слоты свободны у всех выбранных преподавателей.' : 'Расписание загружается с сайта ОмГТУ. В таблице можно выбрать подходящие пары.'}</p></div>
          </aside>

          <section class="results-panel" aria-live="polite">
            <div class="results-header">
              <div>
                <span class="panel-number">02 — РЕЗУЛЬТАТ</span>
                <h2>{uiPage === 'substitutions' ? 'Занятия и доступные замены' : 'Общие свободные окна'}</h2>
              </div>
              <div class="results-header-actions">
                <div class="display-mode-toggle" role="group" aria-label="Режим отображения расписания">
                  <button
                    type="button"
                    class:active={displayMode === 'windows'}
                    aria-pressed={displayMode === 'windows'}
                    title="Цветом показаны окна преподавателя и группы; наведите на слот для подробностей"
                    on:click={() => setDisplayMode('windows')}
                  >
                    Статусы окон
                  </button>
                  <button
                    type="button"
                    class:active={displayMode === 'classic'}
                    aria-pressed={displayMode === 'classic'}
                    title="Обычный вид расписания без цветовых статусов окон и карточек"
                    on:click={() => setDisplayMode('classic')}
                  >
                    Обычный вид
                  </button>
                </div>
                {#if hasGenerated}
                  <span class="week-count">{weeks.length} {weeks.length === 1 ? 'неделя' : weeks.length < 5 ? 'недели' : 'недель'}</span>
                {/if}
              </div>
            </div>
            {#if error}<div class="state-card error-card"><span class="state-icon"><AppIcon name="alert" size={30} /></span><h3>Не удалось получить расписание</h3><p>{error}</p><button type="button" on:click={generate}>Повторить запрос <AppIcon name="arrow-up-right" size={15} /></button></div>
            {:else if loading}<div class="state-card"><span class="state-icon loading-icon"><AppIcon name="clock" size={30} /></span><h3>Сопоставляем расписания</h3><p>{uiPage === 'substitutions' ? 'Загружаем занятия и расписания возможных замещающих преподавателей.' : page === 'meetings' ? 'Загружаем расписания выбранных преподавателей.' : 'Загружаем основного преподавателя, группы и выбранный состав комиссии.'}</p></div>
            {:else if !hasGenerated}<div class="state-card empty-card"><div class="empty-illustration"><span>01</span><span>02</span><span>03</span><span>04</span></div><h3>{uiPage === 'substitutions' ? 'Здесь появятся занятия' : 'Здесь появятся свободные окна'}</h3><p>{uiPage === 'substitutions' ? 'Выберите преподавателя, которого нужно заменить, укажите возможных заменяющих и период. Мы покажем его занятия и доступность коллег.' : page === 'meetings' ? 'Добавьте преподавателей и укажите даты. Мы покажем пары, свободные у всех выбранных.' : `Выберите преподавателя, добавьте группы и укажите даты.${page === 'retakes' && retakeMode === 'commission' ? ' Для комиссии укажите людей или тематическую группу.' : ''} Мы покажем общие свободные пары по неделям.`}</p></div>
            {:else}
              <div class="legend">
                {#if uiPage === 'substitutions'}
                  <span><i class="legend-dot free"></i>Занятие для замены</span>
                  <span><i class="legend-dot selected"></i>Выбрано</span>
                  <span><i class="legend-dot unavailable"></i>Нет занятия</span>
                  <span>Доступность заменяющих указана справочно под слотом</span>
                {:else if displayMode === 'classic'}
                  <span><i class="legend-dot free"></i>Можно выбрать</span>
                  <span><i class="legend-dot selected"></i>Выбрано</span>
                  <span><i class="legend-dot unavailable"></i>{page === 'meetings' ? 'Не все преподаватели свободны' : 'Нет общего окна'}</span>
                  {#if page === 'retakes' && retakeMode === 'commission'}
                    <span>Комиссия указана справочно под слотом</span>
                  {/if}
                {:else}
                  <span><i class="legend-dot window-none"></i>Без окон</span>
                  <span><i class="legend-dot window-teacher"></i>Окно у преподавателя</span>
                  {#if page !== 'meetings'}
                  <span><i class="legend-dot window-group"></i>{groups.length > 1 ? 'Окно у групп' : 'Окно у группы'}</span>
                  <span><i class="legend-dot window-both"></i>Окно и у преподавателя, и у {groups.length > 1 ? 'групп' : 'группы'}</span>
                  {/if}
                  <span><i class="legend-dot selected"></i>Выбрано</span>
                  <span><i class="legend-dot unavailable"></i>Занято</span>
                  {#if page !== 'meetings'}
                  <span><span class="legend-border-sample group"></span> {groups.length > 1 ? 'День без пар у групп' : 'День без пар у группы'}</span>
                  {/if}
                  <span><span class="legend-border-sample teacher"></span> День без пар у преп.</span>
                  {#if page === 'retakes' && retakeMode === 'commission'}
                    <span>Комиссия указана справочно под слотом</span>
                  {/if}
                {/if}
              </div>
              {#if unknownDates > 0}<p class="warning-note">У {unknownDates} занятий не удалось определить дату. Проверьте итог по исходному расписанию.</p>{/if}
              {#if failedCommissionCount > 0}<p class="warning-note">Не удалось загрузить расписание {failedCommissionCount} {failedCommissionCount === 1 ? 'преподавателя' : 'преподавателей'} {uiPage === 'substitutions' ? 'для замены' : page === 'meetings' ? 'для встречи' : 'комиссии'}. {page === 'meetings' ? 'Общие свободные слоты нельзя определить, пока не загрузятся все расписания.' : 'Они не отмечены как доступные.'}</p>{/if}
              {#each weeks as week, index}
                <div class="week-block"><div class="week-title"><div><span>НЕДЕЛЯ {String(index + 1).padStart(2, '0')}</span><h3>{dateShort(week.monday)} — {dateShort(week.saturday)}</h3></div><span>ПН — СБ</span></div>
                  <div class="table-scroll"><div class="schedule-table" role="table" aria-label={`Неделя ${dateShort(week.monday)} — ${dateShort(week.saturday)}`}>
                    <div class="table-row table-head" role="row"><div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>{#each week.dates as date, day}{@const dStatus = week.daysStatus ? week.daysStatus[day] : null}<div role="columnheader" class:today-column={date === currentDateIso} class:col-teacher-free={displayMode === 'windows' && dStatus && dStatus.teacherFreeDay && !dStatus.bothFreeDay} class:col-group-free={displayMode === 'windows' && dStatus && dStatus.groupFreeDay && !dStatus.bothFreeDay} class:col-both-free={displayMode === 'windows' && dStatus && dStatus.bothFreeDay} title={displayMode === 'windows' ? (dStatus?.tooltipText || '') : ''}>{#if displayMode === 'windows'}<div class="head-day-info"><strong>{dayNames[day]}</strong><span>{dateShort(date)}</span></div>{#if dStatus && dStatus.bothFreeDay}<span class="day-col-badge" class:badge-no-lessons={page === 'meetings'} class:badge-both={page !== 'meetings'}>{dStatus.badgeLabel || (groups.length > 1 ? 'Без пар у всех' : 'Без пар у обоих')}</span>{:else if dStatus && dStatus.teacherFreeDay}<span class="day-col-badge badge-teacher">{dStatus.badgeLabel || 'Без пар у преп.'}</span>{:else if dStatus && dStatus.groupFreeDay}<span class="day-col-badge badge-group">{dStatus.badgeLabel || (groups.length > 1 ? 'Без пар у групп' : 'Без пар у группы')}</span>{/if}{:else}<strong>{dayNames[day]}</strong><span>{dateShort(date)}</span>{/if}</div>{/each}</div>
                    {#each week.rows as row, rowIndex}<div class="table-row" role="row"><div class="slot-label" role="rowheader"><strong>{String(row.slot.number).padStart(2, '0')}</strong><span>{row.slot.start}<br />{row.slot.end}</span></div>
                      {#each row.cells as cell, day}{@const dStatus = week.daysStatus ? week.daysStatus[day] : null}<div role="cell" class="cell-wrap" class:today-column={cell.date === currentDateIso} class:col-teacher-free={displayMode === 'windows' && dStatus && dStatus.teacherFreeDay && !dStatus.bothFreeDay} class:col-group-free={displayMode === 'windows' && dStatus && dStatus.groupFreeDay && !dStatus.bothFreeDay} class:col-both-free={displayMode === 'windows' && dStatus && dStatus.bothFreeDay} class:col-last-row={displayMode === 'windows' && rowIndex === week.rows.length - 1}><button type="button" class="slot-cell" class:mode-classic={displayMode === 'classic'} class:is-free={cell.available} class:is-selected={selected.has(cell.key)} class:no-lessons-today={displayMode === 'windows' && cellHasNoLessonsToday(cell)} class:window-none={displayMode === 'windows' && cell.available && cell.windowStatus === 'none'} class:window-group={displayMode === 'windows' && cell.available && cell.windowStatus === 'group-window'} class:window-teacher={displayMode === 'windows' && cell.available && cell.windowStatus === 'teacher-window'} class:window-both={displayMode === 'windows' && cell.available && cell.windowStatus === 'both-window'} class:show-candidates={(uiPage === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && commissionChoice === 'group' && selected.has(cell.key)} disabled={!cell.available} aria-pressed={cell.available ? selected.has(cell.key) : undefined} aria-label={cellAriaLabel(cell, row.slot)} on:mouseenter={(e) => { if (displayMode === 'windows') showTooltip(cell, row.slot, e); }} on:mouseleave={hideTooltip} on:focus={(e) => { if (displayMode === 'windows') showTooltip(cell, row.slot, e); }} on:blur={hideTooltip} on:click={() => toggle(cell)}>
                        {#if selected.has(cell.key) && slotAssignedAuditoriums.has(cell.key)}<span class="cell-assigned-aud-chip">Ауд. {slotAssignedAuditoriums.get(cell.key)?.name}</span>{/if}
                        {#if cell.outOfRange}<span class="cell-muted">Вне периода</span>{:else if displayMode === 'classic'}{#if page === 'meetings'}{#if cell.available}<span class="cell-group-list">Свободны все</span><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{:else}<span class="cell-muted">Занято</span>{/if}{:else if uiPage === 'substitutions'}{#if cell.teacherBusy}<span class="cell-group-list lesson-summary">{cell.lessons.join('; ')}</span><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{:else}<span class="cell-muted">Нет занятия</span>{/if}{:else if cell.teacherBusy}<span class="cell-muted">Занято</span>{:else if !cell.freeGroups.length}<span class="cell-muted">Нет групп</span>{:else}<span class="cell-group-list">{cell.freeGroups.map((group) => group.label).join(', ')}</span><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{/if}{:else}{#if !cell.available}<span class="cell-muted cell-unavailable-reason">{cell.unavailableText ?? 'Занято'}</span>{:else if page === 'meetings'}<div class="cell-free-body">{#if cell.teachersDetails && cell.teachersDetails.length > 0}<div class="cell-chips-wrap">{#each cell.teachersDetails as t}<span class="mini-chip" class:chip-free={t.available && !t.hasWindow} class:chip-teacher-window={t.available && t.hasWindow} class:chip-no-lessons={t.noLessons} class:chip-busy={!t.available && !t.noLessons} title={`${t.person.label}${t.hasWindow ? `: Окно (${formatPairCount(t.windowPairs)})` : ''}`}><span class="mini-chip-label">{t.person.label.split(' ')[0]}</span></span>{/each}</div>{:else}<span class="cell-group-list">Свободно</span>{/if}<span class="cell-status-tag tag-{cell.windowStatus}">{windowStatusShort(cell.windowStatus, cell.windowPairs)}</span></div><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{:else if uiPage === 'substitutions'}<div class="cell-free-body"><span class="cell-group-list lesson-summary">{cell.lessons.join('; ')}</span></div><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{:else}<div class="cell-free-body">{#if cell.groupsDetails && cell.groupsDetails.length > 1}<div class="cell-chips-wrap">{#each cell.groupsDetails as detail}<span class="mini-chip" class:chip-free={!detail.busy && !detail.hasWindow && !detail.noLessonsToday} class:chip-group-window={!detail.busy && detail.hasWindow && !detail.noLessonsToday} class:chip-group-no-lessons={detail.noLessonsToday} class:chip-busy={detail.busy} title={`${detail.group.label}: ${detail.noLessonsToday ? 'нет пар сегодня' : detail.hasWindow ? `Окно (${formatPairCount(detail.windowPairs)})` : detail.busy ? 'занята' : 'без окон'}`}><span class="mini-chip-label">{detail.group.label}</span></span>{/each}</div>{:else if cell.groupsDetails.length === 1 && cell.groupsDetails[0].noLessonsToday}<div class="cell-chips-wrap"><span class="mini-chip chip-group-no-lessons" title={`${cell.groupsDetails[0].group.label}: нет пар сегодня`}><span class="mini-chip-label">{cell.groupsDetails[0].group.label}</span></span></div>{:else}<span class="cell-group-list">{cell.freeGroups.map((group) => group.label).join(', ')}</span>{/if}<span class="cell-status-tag" class:tag-no-lessons={cellHasNoLessonsToday(cell)} class:tag-none={!cellHasNoLessonsToday(cell) && cell.windowStatus === 'none'} class:tag-group-window={!cellHasNoLessonsToday(cell) && cell.windowStatus === 'group-window'} class:tag-teacher-window={!cellHasNoLessonsToday(cell) && cell.windowStatus === 'teacher-window'} class:tag-both-window={!cellHasNoLessonsToday(cell) && cell.windowStatus === 'both-window'}>{cellHasNoLessonsToday(cell) ? 'Нет пар сегодня' : windowStatusShort(cell.windowStatus, cell.windowPairs)}</span></div><span class="cell-check"><AppIcon name={selected.has(cell.key) ? 'check' : 'plus'} size={15} /></span>{/if}{/if}
                        {#if (uiPage === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && commissionChoice === 'group' && selected.has(cell.key)}<span class="selected-commission-names"><span class="candidate-list-label">{uiPage === 'substitutions' ? 'Могут заменить:' : 'Комиссия:'}</span>{#if freeCommission(cell).length}{#each freeCommission(cell) as name}<span class="candidate-name">{name}</span>{/each}{:else}<span class="candidate-name">Никого из группы</span>{/if}</span>{/if}
                      </button>
                      {#if (uiPage === 'substitutions' ? cell.teacherBusy : page === 'retakes' && retakeMode === 'commission' && !cell.outOfRange)}<div class="commission-strip">
                        {#if commissionChoice === 'people'}
                          {#each cell.commission as entry, number}<span class="commission-person-indicator" class:can-attend={entry.available} class:no-lessons={entry.reason === 'no-lessons'} class:load-error={entry.reason === 'load-error'} title={`${entry.person.label}: ${commissionReason(entry.reason)}`} aria-label={`Преподаватель ${number + 1}, ${entry.person.label}: ${commissionReason(entry.reason)}`}>{number + 1} <AppIcon name={entry.available ? 'check' : 'close'} size={12} /></span>{/each}
                        {:else}
                          <span class="commission-count" title={freeCommission(cell).length ? freeCommission(cell).join('\n') : 'Нет доступных преподавателей'} aria-label={`${freeCommission(cell).length} из ${cell.commission.length} преподавателей ${uiPage === 'substitutions' ? 'могут заменить' : 'комиссии могут присутствовать'}`}>{freeCommission(cell).length} из {cell.commission.length} могут</span>
                        {/if}
                      </div>{/if}
                      </div>{/each}
                    </div>{/each}
                  </div></div>
                </div>
              {/each}
              {#if !weeks.some((week) => week.rows.some((row) => row.cells.some((cell) => cell.available)))}<p class="no-free">{uiPage === 'substitutions' ? 'В этом периоде занятий для замены не найдено. Попробуйте изменить даты.' : page === 'meetings' ? 'В этом периоде общих свободных пар не найдено. Попробуйте изменить даты или состав участников.' : 'В этом периоде общих свободных пар не найдено. Попробуйте изменить даты или состав групп.'}</p>{/if}
            {/if}
          </section>
        </div>
      </div>
      {#if hasGenerated}
        <div class="selection-bar" aria-live="polite">
          <button
            type="button"
            class="selection-info selection-trigger"
            on:click={openSelectedSlotsModal}
            title="Открыть список выбранных пар"
          >
            <span class="selection-count">{selectedCount}</span>
            <span class="selection-text">
              <strong>Выбрано {uiPage === 'substitutions' ? 'занятий' : 'слотов'}</strong>
              <small>{selectedCount ? `В ${new Set(selectedDetails.map((item) => item.cell.date)).size} дн. · Посмотреть` : uiPage === 'substitutions' ? 'Нажмите на занятие' : 'Нажмите на свободную пару'}</small>
            </span>
            {#if selectedCount}
              <span class="selection-arrow-icon"><AppIcon name="arrow-up-right" size={18} /></span>
            {/if}
          </button>
          {#if isPlanningPage()}
            <span class="plan-save-state state-{planSaveState}" title={planSaveMessage || (planSaveState === 'saved' ? 'Черновик хранится в аккаунте и будет доступен после входа' : '')} role="status">
              <i></i>{planSaveState === 'loading' ? 'Загружаем план' : planSaveState === 'saving' ? 'Сохраняем' : planSaveState === 'error' ? 'Не сохранено' : 'Сохранено в аккаунте'}
            </span>
          {/if}
          {#if selectedCount && page !== 'meetings'}
            <div class="selection-actions">
              <button type="button" class="btn-aud-finder" on:click={() => openAuditoriumModal('all')}>
                <span>Подобрать аудиторию</span>
                <span class="btn-arrow"><AppIcon name="arrow-up-right" size={18} /></span>
              </button>
              <button type="button" class="btn-clear-selection" on:click={clearSelection}>Очистить</button>
            </div>
          {/if}
        </div>
      {/if}
    {:else if page === 'schedule'}
      <PlannerPageFrame section="ПРОСМОТР" sectionNumber="01" breadcrumb="Группы" title="Расписание групп" description="Расписание выбранных групп на нужный период" icon="▦" on:home={() => go('home')}>
          <PlannerFilterBar slot="filters" ariaLabel="Фильтры расписания" className={viewerGroupMode === 'selected' ? 'viewer-controls viewer-top-controls has-group-selection' : 'viewer-controls viewer-top-controls'}>
            <div class="field-block viewer-stream-picker">
              <div class="field-head">
                <label>Группы</label>
                <span>{viewerGroupCatalogLoading ? '…' : viewerHasGenerated ? `${viewerDisplayEntities.length} из ${viewerScheduleEntities().length}` : viewerScheduleEntities().length}</span>
              </div>
              <div class="viewer-stream-controls">
                <div class="commission-choice" role="group" aria-label="Выбор групп">
                  <button type="button" class:active={viewerGroupMode === 'all'} aria-pressed={viewerGroupMode === 'all'} on:click={() => { viewerGroupMode = 'all'; queueViewerSchedule(); }}>Все группы</button>
                  <button type="button" class:active={viewerGroupMode === 'selected'} aria-pressed={viewerGroupMode === 'selected'} on:click={() => { viewerGroupMode = 'selected'; queueViewerSchedule(); }}>Выбрать группы</button>
                </div>
              </div>
              <div class="viewer-add-group">
                <SearchField type="group" placeholder="Добавить группу по названию" onPick={addViewerGroup} />
              </div>
              {#if viewerGroupCatalogLoading}
                <span class="viewer-catalog-loading"><i></i>Загружаем группы МО и ФИТ…</span>
              {:else if viewerGroupCatalogError}
                <p class="form-error">{viewerGroupCatalogError}</p>
                <button class="viewer-stream-retry" type="button" on:click={() => { viewerGroupCatalogKey = ''; void loadViewerDepartmentGroups(); }}>Повторить загрузку</button>
              {:else if viewerGroupMode === 'selected'}
                <div class="viewer-stream-actions"><span>Выбрано {viewerSelectableGroups.filter((group) => viewerSelectedGroupIds.has(group.id)).length} из {viewerSelectableGroups.length}</span><span><button type="button" on:click={() => selectAllViewerGroups(true)}>Выбрать все</button><button type="button" on:click={() => selectAllViewerGroups(false)}>Снять выбор</button></span></div>
                <div class="viewer-stream-list" aria-label="Доступные группы">
                  {#each viewerGroupColumns as column (column.year)}
                    {@const selectedInYear = column.groups.filter((group) => viewerSelectedGroupIds.has(group.id)).length}
                    <div class="viewer-stream-cohort">
                      <h3>
                        <label class="viewer-stream-cohort-select">
                          <input type="checkbox" checked={selectedInYear === column.groups.length} use:setIndeterminate={selectedInYear > 0 && selectedInYear < column.groups.length} aria-checked={selectedInYear > 0 && selectedInYear < column.groups.length ? 'mixed' : selectedInYear === column.groups.length} aria-label={`Выбрать все группы ${column.year === 'Другие' ? 'без года' : `${column.year} года`}`} on:change={(event) => setViewerYearSelection(column.groups, (event.currentTarget as HTMLInputElement).checked)} />
                          <span>{column.year === 'Другие' ? column.year : `${column.year} год`}</span>
                        </label>
                      </h3>
                      {#each column.groups as group (group.id)}
                        <label><input type="checkbox" checked={viewerSelectedGroupIds.has(group.id)} on:change={() => toggleViewerGroup(group.id)} /><span>{group.label}</span></label>
                      {/each}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>

            <div class="sub-filter viewer-date-filter viewer-start-filter"><label for="viewer-start-date">Период с</label><input id="viewer-start-date" type="date" bind:value={viewerStart} on:change={() => queueViewerSchedule()} /></div>
            <div class="sub-filter viewer-date-filter viewer-end-filter"><label for="viewer-end-date">по</label><input id="viewer-end-date" type="date" min={viewerStart} bind:value={viewerFinish} on:change={() => queueViewerSchedule()} /></div>
            {#if viewerStart && viewerFinish && viewerStart > viewerFinish}
              <p class="form-error">Дата окончания раньше даты начала.</p>
            {/if}

          </PlannerFilterBar>
          <PlannerToolbar slot="toolbar" ariaLabel="Обозначения и настройки расписания">
            <div slot="legend" class="planner-toolbar-legend legend viewer-schedule-legend">
              <span><i class="legend-dot free"></i>Свободно</span>
              <span><i class="legend-dot selected"></i>Занятие</span>
              <span>Подробности о паре — при наведении</span>
            </div>
            <div slot="options" class="planner-toolbar-options viewer-display-options" aria-label="Отображение информации о занятиях">
              <label class="viewer-active-only" class:active={viewerOnlyWithLessons}><input type="checkbox" bind:checked={viewerOnlyWithLessons} on:change={applyViewerDisplayFilter} /><span>Только группы с парами</span></label>
              <label class:active={viewerShowTeacher}><input type="checkbox" bind:checked={viewerShowTeacher} /> Отображать преподавателя</label>
              <label class:active={viewerShowSubject}><input type="checkbox" bind:checked={viewerShowSubject} /> Отображать название</label>
              <label class:active={viewerShowAuditorium}><input type="checkbox" bind:checked={viewerShowAuditorium} /> Отображать аудиторию</label>
            </div>
          </PlannerToolbar>
            {#if viewerGroupCatalogError}
              <div class="state-card error-card">
                <span class="state-icon"><AppIcon name="alert" size={30} /></span>
                <h3>Не удалось загрузить список групп</h3>
                <p>{viewerGroupCatalogError}</p>
                <button type="button" on:click={() => { viewerGroupCatalogKey = ''; void loadViewerDepartmentGroups().then(generateScheduleView); }}>Повторить загрузку <AppIcon name="arrow-up-right" size={15} /></button>
              </div>
            {:else if viewerError}
              <div class="state-card error-card">
                <span class="state-icon"><AppIcon name="alert" size={30} /></span>
                <h3>Не удалось получить расписание</h3>
                <p>{viewerError}</p>
                <button type="button" on:click={generateScheduleView}>Повторить запрос <AppIcon name="arrow-up-right" size={15} /></button>
              </div>
            {:else if viewerGroupCatalogLoading}
              <div class="state-card">
                <span class="state-icon loading-icon"><AppIcon name="clock" size={30} /></span>
                <h3>Загружаем группы кафедры</h3>
                <p>Загружаем список групп МО и ФИТ из расписания ОмГТУ.</p>
              </div>
            {:else if viewerLoading && !viewerHasGenerated}
              <div class="state-card">
                <span class="state-icon loading-icon"><AppIcon name="clock" size={30} /></span>
                <h3>Загружаем расписание из кеша</h3>
                <p>Если снимок устарел или ещё не создан, worker обновляет его постепенно.</p>
              </div>
            {:else if viewerLoading && viewerDisplayEntities.length === 0}
              <div class="state-card">
                <span class="state-icon loading-icon"><AppIcon name="clock" size={30} /></span>
                <h3>Проверяем расписания групп</h3>
                <p>Загружено {viewerLoadedEntities.length} из {viewerScheduleEntities().length}; группы с парами появятся по мере обновления кеша.</p>
              </div>
            {:else if viewerHasGenerated && viewerDisplayEntities.length === 0}
              <div class="state-card empty-card">
                <span class="state-icon"><AppIcon name="clock" size={30} /></span>
                <h3>Нет групп с парами</h3>
                <p>За выбранный период у выбранных групп занятий нет. Отключите фильтр, чтобы показать все группы.</p>
              </div>
            {:else if !viewerHasGenerated}
              <div class="state-card empty-card">
                <div class="empty-illustration">
                  <span>01</span>
                  <span>02</span>
                  <span>03</span>
                  <span>04</span>
                </div>
                <h3>{viewerGroupMode === 'selected' && viewerSelectedGroupIds.size === 0 ? 'Выберите группы' : 'Здесь появится расписание'}</h3>
                <p>{viewerGroupMode === 'selected' && viewerSelectedGroupIds.size === 0 ? 'Отметьте хотя бы одну группу в списке выше — её расписание загрузится автоматически.' : 'Расписание загрузится автоматически после выбора групп и периода.'}</p>
              </div>
            {:else}
              {#if viewerLoading}<p class="aud-data-note" role="status">Расписания загружены для {viewerLoadedEntities.length} из {viewerScheduleEntities().length} групп. Остальные появляются по мере обновления кеша.</p>{/if}
              {#each viewerWeeks as week, index (week.monday)}
                <div class="week-block">
                  <div class="week-title">
                    <div>
                      <span>НЕДЕЛЯ {String(index + 1).padStart(2, '0')}</span>
                      <h3>{dateShort(week.monday)} — {dateShort(week.saturday)}</h3>
                    </div>
                    <span>ПН — СБ</span>
                  </div>

                  <div class="table-scroll">
                    <div class="schedule-table viewer-schedule-table" role="table" aria-label={`Неделя ${dateShort(week.monday)} — ${dateShort(week.saturday)}`}>
                      <div class="table-row table-head" role="row">
                        <div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>
                        {#each week.dates as date, day}
                          <div role="columnheader" class:today-column={date === currentDateIso}>
                            <div class="head-day-info">
                              <strong>{dayNames[day]}</strong>
                              <span>{dateShort(date)}</span>
                            </div>
                          </div>
                        {/each}
                      </div>

                      {#each week.rows as row (row.slot.number)}
                        <div class="table-row" role="row">
                          <div class="slot-label" role="rowheader">
                            <strong>{String(row.slot.number).padStart(2, '0')}</strong>
                            <span>{row.slot.start}<br />{row.slot.end}</span>
                          </div>

                          {#each row.cells as cell (cell.key)}
                            <div role="cell" class="cell-wrap viewer-cell-wrap" class:today-column={cell.date === currentDateIso} class:out-of-range={cell.outOfRange} class:viewer-cell-no-lessons={!cell.lanes.some((lane) => lane.lessons.length > 0)}>
                              {#if cell.outOfRange}
                                <div class="slot-cell out-of-range">
                                  <span class="cell-muted">Вне периода</span>
                                </div>
                              {:else}
                                <div class="viewer-lines-stack">
                                  {#each cell.lanes.filter((lane) => !viewerOnlyWithLessons || lane.lessons.length > 0) as lane (lane.entity.id + lane.entity.type)}
                                    <div
                                      class="viewer-entity-line"
                                      class:line-free={lane.isFree}
                                      class:line-busy={!lane.isFree}
                                      on:mouseenter={(event) => lane.lessons.length === 0 && showViewerStatusTooltip(lane.entity, row.slot, cell.date, event)}
                                      on:mouseleave={hideViewerTooltip}
                                    >
                                      {#if viewerDisplayEntities.length > 1}
                                        <span class="viewer-line-entity" title={lane.entity.label}>
                                          {lane.entity.type === 'person' ? formatShortName(lane.entity.label) : lane.entity.label}:
                                        </span>
                                      {/if}

                                      {#if lane.lessons.length === 0}
                                        <span class="viewer-line-free-dash">—</span>
                                      {:else}
                                        <div class="viewer-line-lessons">
                                          {#each lane.lessons as lesson (lesson.discipline + (lesson.subgroup ?? '') + (lesson.auditorium ?? ''))}
                                            <!-- svelte-ignore a11y-no-static-element-interactions -->
                                            <div
                                              class="viewer-lesson-line"
                                              class:viewer-planned-lesson={Boolean(lesson.planKind)}
                                              tabindex="0"
                                              role="button"
                                              on:mouseenter={(e) => showViewerTooltip(lesson, lane.entity, row.slot, cell.date, e)}
                                              on:mouseleave={hideViewerTooltip}
                                              on:focus={(e) => showViewerTooltip(lesson, lane.entity, row.slot, cell.date, e)}
                                              on:blur={hideViewerTooltip}
                                            >
                                              {#if viewerShowSubject && lesson.kindOfWork}
                                                <span class="viewer-kind-prefix">{formatLessonKindShort(lesson.kindOfWork)}</span>
                                              {/if}
                                              {#if lesson.planKind}
                                                <span class="viewer-plan-badge">{lesson.planKind === 'substitution' ? 'Замена' : lesson.planKind === 'consultation' ? 'Консультация' : lesson.planKind === 'retake' ? 'Пересдача' : 'Встреча'} · {lesson.planStatus === 'confirmed' ? 'подтверждено' : 'выбрано'}</span>
                                              {/if}
                                              {#if viewerShowSubject}<strong class="viewer-lesson-title" title={lesson.discipline}>{lesson.discipline}</strong>{/if}
                                              <span class="viewer-lesson-details">
                                                {#if lesson.subgroup}
                                                  <span class="viewer-subgroup-info">п. {lesson.subgroup}</span>
                                                {/if}
                                                {#if lane.entity.type === 'group'}
                                                  {#if viewerShowAuditorium && lesson.auditorium}
                                                    <span class="viewer-aud-info">ауд. {lesson.auditorium}</span>
                                                  {/if}
                                                  {#if viewerShowTeacher && lesson.lecturer}
                                                    <span class="viewer-person-info" title={lesson.lecturer}>{lesson.lecturer}</span>
                                                  {/if}
                                                {:else if lane.entity.type === 'person'}
                                                  {#if viewerShowAuditorium && lesson.auditorium}
                                                    <span class="viewer-aud-info">ауд. {lesson.auditorium}</span>
                                                  {/if}
                                                  {#if lesson.group}
                                                    <span class="viewer-person-info" title={lesson.group}>{lesson.group}</span>
                                                  {/if}
                                                {:else}
                                                  {#if lesson.group}
                                                    <span class="viewer-person-info" title={lesson.group}>{lesson.group}</span>
                                                  {/if}
                                                  {#if viewerShowTeacher && lesson.lecturer}
                                                    <span class="viewer-person-info" title={lesson.lecturer}>{lesson.lecturer}</span>
                                                  {/if}
                                                {/if}
                                              </span>
                                            </div>
                                          {/each}
                                        </div>
                                      {/if}
                                    </div>
                                  {/each}
                                </div>
                              {/if}
                            </div>
                          {/each}
                        </div>
                      {/each}
                    </div>
                  </div>
                </div>
              {/each}
            {/if}
      </PlannerPageFrame>
    {/if}
  </main>

  <footer class="footer"><span><strong>Запара</strong> / пространство преподавателя</span><span>Разработал ассистент кафедры ПМиФИ Плескунов Д.А.</span></footer>

  {#if activeTooltip && displayMode === 'windows'}
    {@const cell = activeTooltip.cell}
    {@const slot = activeTooltip.slot}
    <div
      class="custom-tooltip"
      style="left: -9999px; top: -9999px;"
      use:fitTooltip={activeTooltip.targetRect}
      role="tooltip"
    >
      <div class="tooltip-header">
        <span class="tooltip-time">{formatDate(cell.date, { weekday: 'short', day: 'numeric', month: 'short' })} · {slot.number} пара ({slot.start}–{slot.end})</span>
        <span class="tooltip-badge status-{cell.available ? (cellHasNoLessonsToday(cell) ? 'no-lessons' : selected.has(cell.key) ? 'selected' : cell.windowStatus) : 'unavailable'}">
          {#if cell.outOfRange}
            Вне периода
          {:else if !cell.available}
            {cell.unavailableText ?? 'Занято'}
          {:else if cellHasNoLessonsToday(cell)}
            Нет пар сегодня
          {:else if selected.has(cell.key)}
            Выбрано
          {:else if cell.windowStatus === 'both-window'}
            {windowStatusShort(cell.windowStatus, cell.windowPairs)}
          {:else}
            {windowStatusShort(cell.windowStatus, cell.windowPairs)}
          {/if}
        </span>
      </div>

      <div class="tooltip-body">
        {#if cell.outOfRange}
          <div class="tooltip-party-row">
            <span class="party-status muted">Дата находится за пределами выбранного диапазона.</span>
          </div>
        {:else if page === 'meetings'}
          {#if cell.teachersDetails && cell.teachersDetails.length}
            <div class="tooltip-section">
              <span class="party-label">Преподаватели ({cell.teachersDetails.length}):</span>
              <div class="tooltip-items-list">
                {#each cell.teachersDetails as t}
                  <div class="tooltip-entity-card" class:card-free={t.available && !t.hasWindow && !t.noLessons} class:card-teacher-window={t.available && t.hasWindow && !t.noLessons} class:card-no-lessons={t.noLessons || (t.available && !t.hasWindow)} class:card-busy={!t.available && !t.noLessons}>
                    <div class="entity-head">
                      <strong class="entity-title">{t.person.label}</strong>
                      <span class="entity-badge">{t.noLessons ? 'нет пар' : !t.available ? 'занят' : t.hasWindow ? `Окно (${formatPairCount(t.windowPairs)})` : 'без окон'}</span>
                    </div>
                    <div class="entity-desc">
                      {#if t.noLessons}
                        <span>В этот день пар нет</span>
                      {:else if !t.available}
                        {#if t.lessonDetails && t.lessonDetails.length}
                          <div class="entity-lessons-wrap">
                            {#each t.lessonDetails as l}
                              <div class="entity-lesson-block">
                                <span class="entity-lesson-name">{l.discipline}</span>
                                <div class="entity-lesson-meta">
                                  {#if l.auditorium}
                                    <span class="lesson-meta-pill">ауд. {l.auditorium}</span>
                                  {/if}
                                  {#if l.group}
                                    <span class="lesson-meta-pill">{l.group}</span>
                                  {/if}
                                </div>
                              </div>
                            {/each}
                          </div>
                        {:else}
                          <span>{commissionReason(t.reason)}</span>
                        {/if}
                      {:else if t.hasWindow}
                        <span>Свободен, окно: {formatPairCount(t.windowPairs)}</span>
                      {:else}
                        <span>Свободен (пара без окон)</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        {:else if uiPage === 'substitutions'}
          {#if cell.teacherBusy}
            <div class="tooltip-section">
              <span class="party-label">Занятие преподавателя:</span>
              <div class="entity-lessons-wrap">
                {#each cell.lessonDetails as l}
                  <div class="tooltip-lesson-item">
                    <strong class="entity-lesson-name">{l.discipline}</strong>
                    <div class="entity-lesson-meta">
                      {#if l.auditorium}
                        <span class="lesson-meta-pill">ауд. {l.auditorium}</span>
                      {/if}
                      {#if l.group}
                        <span class="lesson-meta-pill">{l.group}</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {:else}
            <div class="tooltip-party-row">
              <span class="party-status muted">У преподавателя нет занятий в это время.</span>
            </div>
          {/if}
        {:else}
          <div class="tooltip-section">
            <span class="party-label">Преподаватель:</span>
            <div class="tooltip-entity-card" class:card-free={!cell.teacherBusy && !cell.teacherHasWindow && !cell.teacherNoLessonsToday} class:card-no-lessons={cell.teacherNoLessonsToday} class:card-teacher-window={!cell.teacherBusy && cell.teacherHasWindow && !cell.teacherNoLessonsToday} class:card-busy={cell.teacherBusy && !cell.teacherNoLessonsToday}>
              <div class="entity-head">
                <strong class="entity-title">{teacher ? teacher.label : 'Преподаватель'}</strong>
                <span class="entity-badge">{cell.teacherNoLessonsToday ? 'нет пар сегодня' : cell.teacherBusy ? 'занят' : cell.teacherHasWindow ? `Окно (${formatPairCount(cell.teacherWindowPairs)})` : 'без окон'}</span>
              </div>
              <div class="entity-desc">
                {#if cell.teacherNoLessonsToday}
                  <span>Сегодня у преподавателя нет пар</span>
                {:else if cell.teacherBusy}
                  {#if cell.lessonDetails && cell.lessonDetails.length}
                    <div class="entity-lessons-wrap">
                      {#each cell.lessonDetails as l}
                        <div class="entity-lesson-block">
                          <span class="entity-lesson-name">{l.discipline}</span>
                          <div class="entity-lesson-meta">
                            {#if l.auditorium}
                              <span class="lesson-meta-pill">ауд. {l.auditorium}</span>
                            {/if}
                            {#if l.group}
                              <span class="lesson-meta-pill">{l.group}</span>
                            {/if}
                          </div>
                        </div>
                      {/each}
                    </div>
                  {:else}
                    <span class="entity-lesson">Занятие</span>
                  {/if}
                {:else if cell.teacherHasWindow}
                  <span>Свободен, окно: {formatPairCount(cell.teacherWindowPairs)}</span>
                {:else}
                  <span>Свободен (пара без окон)</span>
                {/if}
              </div>
            </div>
          </div>

          {#if cell.groupsDetails && cell.groupsDetails.length}
            <div class="tooltip-section">
              <span class="party-label">Учебные группы ({cell.groupsDetails.length}):</span>
              <div class="tooltip-items-list">
                {#each cell.groupsDetails as detail}
                  <div class="tooltip-entity-card" class:card-free={!detail.busy && !detail.hasWindow && !detail.noLessonsToday} class:card-group-window={!detail.busy && detail.hasWindow && !detail.noLessonsToday} class:card-no-lessons={detail.noLessonsToday} class:card-busy={detail.busy}>
                    <div class="entity-head">
                      <strong class="entity-title">{detail.group.label}</strong>
                      <span class="entity-badge">{detail.noLessonsToday ? 'нет пар сегодня' : detail.busy ? 'занята' : detail.hasWindow ? `Окно (${formatPairCount(detail.windowPairs)})` : 'без окон'}</span>
                    </div>
                    <div class="entity-desc">
                      {#if detail.busy}
                        {#if detail.lessonDetails && detail.lessonDetails.length}
                          <div class="entity-lessons-wrap">
                            {#each detail.lessonDetails as l}
                              <div class="entity-lesson-block">
                                <span class="entity-lesson-name">{l.discipline}</span>
                                <div class="entity-lesson-meta">
                                  {#if l.lecturer}
                                    <span class="lesson-meta-pill">{l.lecturer}</span>
                                  {/if}
                                  {#if l.auditorium}
                                    <span class="lesson-meta-pill">ауд. {l.auditorium}</span>
                                  {/if}
                                </div>
                              </div>
                            {/each}
                          </div>
                        {:else}
                          <span class="entity-lesson">Занятие</span>
                        {/if}
                      {:else if detail.noLessonsToday}
                        <span>Сегодня у группы нет пар</span>
                      {:else if detail.hasWindow}
                        <span>Свободна, окно: {formatPairCount(detail.windowPairs)}</span>
                      {:else}
                        <span>Свободна (пара без окон)</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        {/if}

        {#if cell.auditoriumsDetails && cell.auditoriumsDetails.length}
          <div class="tooltip-section">
            <span class="party-label">Аудитории ({cell.auditoriumsDetails.length}):</span>
            <div class="tooltip-items-list">
              {#each cell.auditoriumsDetails as detail}
                <div class="tooltip-entity-card" class:card-free={!detail.busy} class:card-busy={detail.busy}>
                  <div class="entity-head">
                    <strong class="entity-title">Ауд. {detail.auditorium.label}</strong>
                    <span class="entity-badge">{detail.busy ? 'занята' : 'свободна'}</span>
                  </div>
                  <div class="entity-desc">
                    {#if detail.busy}
                      {#if detail.lessonDetails && detail.lessonDetails.length}
                        <div class="entity-lessons-wrap">
                          {#each detail.lessonDetails as l}
                            <div class="entity-lesson-block">
                              <span class="entity-lesson-name">{l.discipline}</span>
                              <div class="entity-lesson-meta">
                                {#if l.lecturer}
                                  <span class="lesson-meta-pill">{l.lecturer}</span>
                                {/if}
                                {#if l.group}
                                  <span class="lesson-meta-pill">{l.group}</span>
                                {/if}
                              </div>
                            </div>
                          {/each}
                        </div>
                      {:else}
                        <span class="entity-lesson">Занятие</span>
                      {/if}
                    {:else}
                      <span>Свободна в это время</span>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  {#if activeViewerTooltip}
    {@const item = activeViewerTooltip}
    {@const lesson = item.lesson}
    <div
      class="custom-tooltip"
      style="left: -9999px; top: -9999px;"
      use:fitTooltip={item.targetRect}
      role="tooltip"
    >
      <div class="tooltip-header">
        <span class="tooltip-time">
          {formatDate(item.date, { weekday: 'short', day: 'numeric', month: 'short' })} · {item.slot.number} пара ({item.slot.start}–{item.slot.end})
        </span>
        <span class="tooltip-badge status-selected">
          {item.entity.type === 'group' ? 'Группа ' : item.entity.type === 'person' ? 'Преподаватель ' : 'Ауд. '}{item.entity.label}
        </span>
      </div>

      <div class="tooltip-body">
        <div class="tooltip-section">
          <div class="tooltip-entity-card card-free">
            {#if lesson}
              <div class="entity-head">
                <strong class="entity-title">{lesson.discipline}</strong>
                {#if lesson.planKind}<span class="entity-badge">{lesson.planKind === 'substitution' ? 'Замена' : lesson.planKind === 'consultation' ? 'Консультация' : lesson.planKind === 'retake' ? 'Пересдача' : 'Встреча'} · {lesson.planStatus === 'confirmed' ? 'подтверждено' : 'выбрано'}</span>{/if}
                {#if lesson.kindOfWork}
                  <span class="entity-badge">{lesson.kindOfWork}</span>
                {/if}
              </div>
              <div class="entity-desc">
                <div class="tooltip-meta-stack">
                  {#if lesson.lecturer}
                    <div class="tooltip-meta-line">
                      <span class="party-label">Преподаватель:</span>
                      <strong>{lesson.lecturer}</strong>
                    </div>
                  {/if}
                  {#if lesson.group}
                    <div class="tooltip-meta-line">
                      <span class="party-label">Группа:</span>
                      <strong>{lesson.group}{#if lesson.subgroup} (подгр. {lesson.subgroup}){/if}</strong>
                    </div>
                  {/if}
                  {#if lesson.auditorium}
                    <div class="tooltip-meta-line">
                      <span class="party-label">Аудитория:</span>
                      <strong>ауд. {lesson.auditorium}{#if lesson.building} ({lesson.building}){/if}</strong>
                    </div>
                  {/if}
                  {#if lesson.timeStart && lesson.timeEnd}
                    <div class="tooltip-meta-line">
                      <span class="party-label">Время:</span>
                      <span>{lesson.timeStart}–{lesson.timeEnd}</span>
                    </div>
                  {/if}
                </div>
              </div>
            {:else}
              <div class="entity-head">
                <strong class="entity-title">Нет занятия на эту пару</strong>
                <span class="entity-badge">Свободно</span>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}

  {#if showAudModal}
    <div
      class="modal-backdrop"
      on:click={closeAuditoriumModal}
      on:keydown={(e) => e.key === 'Escape' && closeAuditoriumModal()}
      role="dialog"
      aria-modal="true"
      tabindex="-1"
    >
      <div class="aud-modal-window" on:click|stopPropagation>
        <div class="aud-modal-header">
          <div>
            <span class="section-kicker">ПОДБОР АУДИТОРИИ</span>
            <h3>Свободные аудитории</h3>
            <p class="modal-subtitle">
              {#if modalTargetSlotDetail}
                На пару: <strong>{formatDate(modalTargetSlotDetail.cell.date, { weekday: 'short', day: 'numeric', month: 'short' })}, {modalTargetSlotDetail.slot.number} пара ({modalTargetSlotDetail.slot.start}–{modalTargetSlotDetail.slot.end})</strong>
              {:else if selectedCount === 1}
                На пару: <strong>{formatDate(selectedDetails[0].cell.date, { weekday: 'short', day: 'numeric', month: 'short' })}, {selectedDetails[0].slot.number} пара ({selectedDetails[0].slot.start}–{selectedDetails[0].slot.end})</strong>
              {:else}
                На все выбранные пары (<strong>{selectedCount}</strong>): {selectedDetails.map((d) => `${dateShort(d.cell.date)} (${d.slot.number} пара)`).join(', ')}
              {/if}
            </p>
          </div>
          <button type="button" class="modal-close-button" on:click={closeAuditoriumModal} aria-label="Закрыть"><AppIcon name="close" size={18} /></button>
        </div>

        {#if selectedDetails.length > 1}
          <div class="modal-slots-tabs">
            <span class="slots-tabs-label">Подобрать для:</span>
            <div class="slots-tabs-list">
              <button
                type="button"
                class="modal-slot-tab"
                class:active={modalTargetSlotKey === 'all'}
                on:click={() => { modalTargetSlotKey = 'all'; updateModalAvailability(); }}
              >
                Всех пар разом ({selectedDetails.length})
              </button>
              {#each selectedDetails as d (d.cell.key)}
                <button
                  type="button"
                  class="modal-slot-tab"
                  class:active={modalTargetSlotKey === d.cell.key}
                  on:click={() => { modalTargetSlotKey = d.cell.key; updateModalAvailability(); }}
                >
                  {dateShort(d.cell.date)} · {d.slot.number} пара
                </button>
              {/each}
            </div>
          </div>
        {/if}

        <div class="aud-modal-controls">
          <div class="modal-control-row">
            <div class="modal-field modal-building-field">
              <label for="modal-building-select">Корпус</label>
              <CustomSelect
                id="modal-building-select"
                size="sm"
                ariaLabel="Корпус"
                bind:value={modalBuildingOid}
                loading={loadingBuildings}
                options={availableBuildings.map((b) => ({ value: b.buildingOid, label: b.name }))}
                on:change={(e) => {
                  modalBuildingOid = e.detail;
                  loadModalBuildingData();
                }}
              />
            </div>

            <div class="modal-field modal-search-field">
              <label for="modal-search-input">Поиск</label>
              <input id="modal-search-input" type="search" placeholder="Номер или название..." bind:value={modalSearchQuery} />
            </div>

            <div class="modal-field modal-capacity-field">
              <label for="modal-capacity-select">Вместимость</label>
              <CustomSelect
                id="modal-capacity-select"
                size="sm"
                ariaLabel="Вместимость"
                bind:value={modalMinCapacity}
                options={[
                  { value: 0, label: 'Любая' },
                  { value: 15, label: 'От 15 мест' },
                  { value: 25, label: 'От 25 мест' },
                  { value: 40, label: 'От 40 мест' },
                  { value: 60, label: 'От 60 мест' },
                  { value: 80, label: 'От 80 мест' }
                ]}
              />
            </div>

            {#if groups.length > 1}
              <div class="modal-field modal-group-field">
                <label for="modal-group-select">Для группы</label>
                <CustomSelect
                  id="modal-group-select"
                  size="sm"
                  ariaLabel="Для группы"
                  bind:value={modalGroupFilter}
                  options={[
                    { value: 'all', label: 'Для всех групп' },
                    ...groups.map((g) => ({ value: g.id, label: g.label }))
                  ]}
                />
              </div>
            {/if}
          </div>

          <div class="modal-types-row">
            <span class="modal-types-label">Типы:</span>
            <div class="modal-type-chips">
              {#each AUDITORIUM_TYPE_CATEGORIES as cat (cat.id)}
                <button
                  type="button"
                  class="modal-type-chip"
                  class:active={modalAudTypes.has(cat.id)}
                  on:click={() => toggleModalAudType(cat.id)}
                >
                  {cat.label}
                </button>
              {/each}
              {#if modalAudTypes.size > 0}
                <button type="button" class="modal-type-reset" on:click={() => modalAudTypes = new Set()}>Сбросить</button>
              {/if}
            </div>
          </div>
        </div>

        <div class="aud-modal-body">
          {#if modalLoading}
            <div class="modal-state-msg">
              <span class="search-spinner"></span>
              <p>Проверяем расписание корпуса на выбранные пары…</p>
            </div>
          {:else if modalError}
            <div class="modal-state-msg modal-error">
              <span>!</span>
              <p>{modalError}</p>
              <button type="button" class="modal-retry-btn" on:click={loadModalBuildingData}>Повторить запрос</button>
            </div>
          {:else if !modalFilteredAvailability.length}
            <div class="modal-state-msg">
              <p><strong>Свободных аудиторий не найдено</strong></p>
              <p class="muted">Попробуйте выбрать другой корпус, снизить вместимость или снять фильтры по типу аудитории.</p>
            </div>
          {:else}
            <div class="modal-results-summary">
              <span>Свободно аудиторий: <strong>{modalFilteredAvailability.length}</strong></span>
              {#if modalFilteredAvailability.length !== modalAvailability.filter((a) => a.freeAll).length}
                <small class="muted">(отфильтровано из {modalAvailability.filter((a) => a.freeAll).length})</small>
              {/if}
            </div>
            <div class="modal-aud-grid">
              {#each modalFilteredAvailability as item (item.auditorium.auditoriumOid)}
                {@const aud = item.auditorium}
                {@const isAlreadyAdded = auditoriums.some((a) => a.id === String(aud.auditoriumOid))}
                <div class="modal-aud-card" class:card-added={isAlreadyAdded}>
                  <div class="modal-aud-top">
                    <span class="modal-aud-num">{aud.name || aud.number}</span>
                    {#if aud.amount}
                      <span class="modal-aud-cap">{aud.amount} мест</span>
                    {/if}
                  </div>
                  <div class="modal-aud-type">{aud.typeOfAuditorium || 'Аудитория'}</div>
                  {#if aud.computerEquipment || aud.mediaEquipment}
                    <div class="modal-aud-equip">
                      {#if aud.computerEquipment}<span class="equip-tag">{aud.computerEquipment} ПК</span>{/if}
                      {#if aud.mediaEquipment}<span class="equip-tag">Проектор</span>{/if}
                    </div>
                  {/if}
                  <div class="modal-aud-bottom">
                    <span class="aud-free-badge">Свободна</span>
                    {#if isAlreadyAdded}
                      <button type="button" class="btn-aud-pick added" on:click={() => removeAuditorium(String(aud.auditoriumOid))}>Добавлена <AppIcon name="close" size={15} /></button>
                    {:else}
                      <button type="button" class="btn-aud-pick" on:click={() => pickAuditoriumFromModal(aud)}>Выбрать <AppIcon name="arrow-up-right" size={15} /></button>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}

  {#if showSelectedModal}
    <div
      class="modal-backdrop"
      on:click={closeSelectedSlotsModal}
      on:keydown={(e) => e.key === 'Escape' && closeSelectedSlotsModal()}
      role="dialog"
      aria-modal="true"
      tabindex="-1"
    >
      <div class="selected-modal-window" on:click|stopPropagation>
        <div class="aud-modal-header">
          <div>
            <span class="section-kicker">ВЫБРАННЫЕ ПАРЫ</span>
            <h3>Список выбранных слотов</h3>
            <p class="modal-subtitle">
              Всего выбрано: <strong>{selectedCount}</strong> {selectedCount === 1 ? 'пара' : selectedCount < 5 ? 'пары' : 'пар'} в <strong>{new Set(selectedDetails.map((item) => item.cell.date)).size}</strong> {new Set(selectedDetails.map((item) => item.cell.date)).size === 1 ? 'дне' : 'днях'}
            </p>
          </div>
          <button type="button" class="modal-close-button" on:click={closeSelectedSlotsModal} aria-label="Закрыть"><AppIcon name="close" size={18} /></button>
        </div>

        <div class="selected-modal-body">
          {#if !selectedDetails.length}
            <div class="modal-state-msg">
              <p><strong>Нет выбранных слотов</strong></p>
              <p class="muted">Нажмите на свободные ячейки в сетке расписания, чтобы добавить их.</p>
            </div>
          {:else}
            <div class="selected-slots-list">
              {#each selectedDetails as item (item.cell.key)}
                <div class="selected-slot-row">
                  <div class="selected-slot-info">
                    <div class="selected-slot-time-badge">
                      <strong>{item.slot.number} пара</strong>
                      <span>{item.slot.start}–{item.slot.end}</span>
                    </div>
                    <div class="selected-slot-details">
                      <span class="selected-slot-date">
                        {formatDate(item.cell.date, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })}
                      </span>
                      <div class="selected-slot-tags">
                        {#if displayMode === 'windows' && item.cell.windowStatus !== 'none'}
                          <span class="slot-badge tag-{item.cell.windowStatus}">
                            {windowStatusShort(item.cell.windowStatus, item.cell.windowPairs)}
                          </span>
                        {/if}
                        {#if page === 'meetings'}
                          <span class="slot-badge slot-badge-group">Преподаватели свободны</span>
                        {:else if item.cell.freeGroups.length}
                          <span class="slot-badge slot-badge-group">
                            {item.cell.freeGroups.map((g) => g.label).join(', ')}
                          </span>
                        {/if}
                        {#if slotAssignedAuditoriums.has(item.cell.key)}
                          {@const aud = slotAssignedAuditoriums.get(item.cell.key)}
                          <span class="slot-badge slot-badge-aud assigned">
                            <strong>Ауд. {aud.name}</strong>
                            {#if aud.capacity}<span class="badge-sub">{aud.capacity} мест</span>{/if}
                            {#if aud.building}<span class="badge-sub">{aud.building}</span>{/if}
                            <button
                              type="button"
                              class="badge-remove-btn"
                              on:click|stopPropagation={() => removeSlotAssignedAud(item.cell.key)}
                              title="Убрать аудиторию с этой пары"
                              aria-label="Убрать аудиторию"
                            ><AppIcon name="close" size={16} /></button>
                          </span>
                        {:else if item.cell.freeAuditoriums && item.cell.freeAuditoriums.length > 0}
                          <span class="slot-badge slot-badge-aud auto-free">
                            <strong>Ауд. {item.cell.freeAuditoriums.map((a) => a.label).join(', ')}</strong>
                            <span class="badge-sub">свободна</span>
                          </span>
                        {/if}
                      </div>
                    </div>
                  </div>

                  <div class="selected-slot-actions">
                    <button
                      type="button"
                      class="btn-slot-aud"
                      on:click={() => findAuditoriumForSlot(item.cell.key)}
                      title="Подобрать аудиторию на эту пару"
                    >
                      {slotAssignedAuditoriums.has(item.cell.key) ? 'Сменить аудиторию' : 'Подобрать аудиторию'} <AppIcon name="arrow-up-right" size={15} />
                    </button>
                    <button
                      type="button"
                      class="btn-slot-remove"
                      on:click={() => removeSelectedSlot(item.cell.key)}
                      aria-label="Удалить пару из выбранных"
                      title="Убрать"
                    >
                      <AppIcon name="close" size={16} />
                    </button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>

        <div class="selected-modal-footer">
          <button type="button" class="btn-clear-all" on:click={clearSelection}>Очистить всё</button>
          <div class="selected-footer-right">
            <button type="button" class="btn-modal-aud-all" on:click={() => findAuditoriumForSlot('all')}>
              Подобрать на все пары <AppIcon name="arrow-up-right" size={15} />
            </button>
            <button type="button" class="btn-modal-done" on:click={closeSelectedSlotsModal}>Готово</button>
          </div>
        </div>
      </div>
    </div>
  {/if}

  {#if toastMessage}
    <div class="app-toast" role="status">
      <span>{toastMessage}</span>
    </div>
  {/if}
</div>
