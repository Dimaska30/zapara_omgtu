<script lang="ts">
  import { onMount } from 'svelte';
  import CustomSelect from './CustomSelect.svelte';
  import SearchField from './SearchField.svelte';
  import {
    AUDITORIUM_TYPE_CATEGORIES,
    DEFAULT_BUILDINGS,
    SLOTS,
    addDays,
    buildViewerWeeks,
    buildWeeks,
    checkAuditoriumsAvailability,
    formatDate,
    formatLessonKindShort,
    formatShortName,
    getAuditoriums,
    getBuildings,
    getBuildingSchedule,
    getSchedule,
    matchesAuditoriumType,
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

  type Page = 'home' | 'consultations' | 'retakes' | 'substitutions' | 'meetings' | 'schedule';
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
  const sections: { page: Page; number: string; name: string; description: string; icon: string; active: boolean }[] = [
    { page: 'retakes', number: '01', name: 'Пересдачи', description: 'Подберите время для повторной сдачи', icon: '↗', active: true },
    { page: 'consultations', number: '02', name: 'Консультации', description: 'Найдите общие свободные окна', icon: '◷', active: true },
    { page: 'substitutions', number: '03', name: 'Замены', description: 'Найдите коллег для замены занятий', icon: '⇄', active: true },
    { page: 'meetings', number: '04', name: 'Рабочие встречи', description: 'Найдите общее время для коллег', icon: '✧', active: true },
    { page: 'schedule', number: '05', name: 'Расписание', description: 'Сравнение расписания групп, преподавателей и аудиторий', icon: '▦', active: true }
  ];
  const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

  let page: Page = 'home';
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
  let viewerEntities: ScheduleViewerEntity[] = [];
  let viewerActiveType: 'group' | 'person' | 'auditorium' = 'group';
  let viewerStart: string = toIso(new Date());
  let viewerFinish: string = toIso(addDays(new Date(), 21));
  let viewerWeeks: ViewerWeek[] = [];
  let viewerLoading: boolean = false;
  let viewerError: string | null = null;
  let viewerHasGenerated: boolean = false;

  type ActiveViewerTooltip = {
    lesson: ViewerLessonDetail;
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

  function hideViewerTooltip() {
    activeViewerTooltip = null;
  }

  function addScheduleViewerEntity(item: SearchItem, entityType: 'group' | 'person' | 'auditorium') {
    if (viewerEntities.some((e) => e.id === item.id && e.type === entityType)) return;
    viewerEntities = [
      ...viewerEntities,
      {
        id: item.id,
        label: item.label,
        type: entityType
      }
    ];
    if (viewerHasGenerated) {
      void generateScheduleView();
    }
  }

  function removeScheduleViewerEntity(id: string, entityType: 'group' | 'person' | 'auditorium') {
    viewerEntities = viewerEntities.filter((e) => !(e.id === id && e.type === entityType));
    if (viewerEntities.length === 0) {
      viewerWeeks = [];
      viewerHasGenerated = false;
      return;
    }
    if (viewerHasGenerated) {
      void generateScheduleView();
    }
  }

  async function generateScheduleView() {
    if (viewerEntities.length === 0) {
      viewerError = 'Выберите хотя бы одну группу, преподавателя или аудиторию.';
      return;
    }
    viewerLoading = true;
    viewerError = null;
    try {
      const entityEventsMap = new Map<string, ApiItem[]>();
      await Promise.all(
        viewerEntities.map(async (entity) => {
          try {
            const events = await getSchedule(entity.type, entity.id, viewerStart, viewerFinish);
            entityEventsMap.set(entity.id, events);
          } catch (e) {
            console.error(`Failed to load schedule for ${entity.label}:`, e);
            entityEventsMap.set(entity.id, []);
          }
        })
      );
      viewerWeeks = buildViewerWeeks(viewerStart, viewerFinish, viewerEntities, entityEventsMap);
      viewerHasGenerated = true;
    } catch (e: any) {
      viewerError = e?.message ?? 'Не удалось загрузить расписание для выбранных объектов';
    } finally {
      viewerLoading = false;
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
  let loadedSchedule: LoadedSchedule | null = null;
  $: selectedCount = selected.size;
  $: selectedDetails = weeks.flatMap((week) => week.rows.flatMap((row) => row.cells.filter((cell) => selected.has(cell.key)).map((cell) => ({ cell, slot: row.slot }))));
  $: selectedCommissionGroup = COMMISSION_GROUPS.find((group) => group.id === commissionGroupId);

  function invalidate() {
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
    ensureBuildings();
    const handleScroll = () => {
      hideTooltip();
      hideViewerTooltip();
    };
    window.addEventListener('scroll', handleScroll, { capture: true, passive: true });
    return () => {
      window.removeEventListener('scroll', handleScroll, true);
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
    }
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

  function chooseTeacher(item: SearchItem) { invalidate(); committeeError = ''; teacher = item; commissionTeachers = commissionTeachers.filter((person) => person.id !== item.id); }
  function removeTeacher() { invalidate(); committeeError = ''; teacher = null; }
  function changeRetakeMode(mode: 'first' | 'commission') { if (retakeMode !== mode) { invalidate(); retakeMode = mode; committeeError = ''; } }
  function changeCommissionChoice(choice: 'people' | 'group') { if (commissionChoice !== choice) { invalidate(); commissionChoice = choice; committeeError = ''; } }
  function changeCommissionGroup(id: string) { invalidate(); commissionGroupId = id; }
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
  }
  function removeCommissionTeacher(id: string) { invalidate(); committeeError = ''; commissionTeachers = commissionTeachers.filter((person) => person.id !== id); }
  function addMeetingTeacher(item: SearchItem) {
    if (meetingTeachers.some((person) => person.id === item.id)) { meetingError = 'Этот преподаватель уже добавлен.'; return; }
    invalidate();
    meetingError = '';
    meetingTeachers = [...meetingTeachers, item];
  }
  function removeMeetingTeacher(id: string) { invalidate(); meetingError = ''; meetingTeachers = meetingTeachers.filter((person) => person.id !== id); }
  function addGroup(item: SearchItem) {
    if (groups.some((group) => group.id === item.id)) return;
    invalidate();
    groups = [...groups, item];
  }
  function removeGroup(id: string) { invalidate(); groups = groups.filter((group) => group.id !== id); }
  function changeStart(value: string) { invalidate(); start = value; }
  function changeFinish(value: string) { invalidate(); finish = value; }

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
    invalidate();
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
      failedCommissionCount = commissionSchedules.failedIds.size;
      hasGenerated = true;
    } catch (cause) {
      if (current === requestNumber && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        error = cause instanceof Error ? cause.message : 'Не удалось загрузить расписание.';
      }
    } finally {
      if (current === requestNumber) loading = false;
    }
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

  function go(next: Page) { if (next !== page) { invalidate(); auditoriums = []; } if (next === 'retakes' && commissionTeachers.length > 2) commissionTeachers = commissionTeachers.slice(0, 2); page = next; window.scrollTo({ top: 0, behavior: 'smooth' }); }
  function dateShort(value: string) { return formatDate(value, { day: '2-digit', month: '2-digit' }); }
  function freeCommission(cell: Cell) { return cell.commission.filter((entry) => entry.available).map((entry) => entry.person.label); }
  function commissionReason(reason: 'free' | 'busy' | 'no-lessons' | 'load-error') { return reason === 'free' ? (page === 'substitutions' ? 'может заменить' : 'может присутствовать') : reason === 'busy' ? 'занят в это время' : reason === 'no-lessons' ? 'нет пар в этот день' : 'расписание не загрузилось'; }
  function windowStatusShort(status: WindowStatus) {
    if (page === 'meetings') {
      if (status === 'teacher-window') return 'Окно у преп.';
      if (status === 'both-window') return 'Окно у всех';
      return 'Без окон';
    }
    if (status === 'group-window') return groups.length > 1 ? 'Окно у групп' : 'Окно у группы';
    if (status === 'teacher-window') return 'Окно у преп.';
    if (status === 'both-window') return groups.length > 1 ? 'Окно у преп. и групп' : 'Окно у преп. и группы';
    return 'Без окон';
  }
  function windowStatusFull(cell: Cell) {
    if (page === 'meetings') {
      const teachersWithWindow = cell.teachersDetails?.filter((t) => t.hasWindow).map((t) => t.person.label) ?? [];
      if (teachersWithWindow.length === 0) return 'без окон';
      if (teachersWithWindow.length === (cell.teachersDetails?.length ?? 0)) return 'окно у всех преподавателей';
      return `окно у: ${teachersWithWindow.join(', ')}`;
    }
    if (cell.windowStatus === 'group-window') {
      if (cell.freeGroupsWithWindow && cell.freeGroupsWithWindow.length > 0 && cell.freeGroups.length > 1) {
        if (cell.freeGroupsWithWindow.length === cell.freeGroups.length) {
          return 'окно у всех групп';
        }
        return `окно у ${cell.freeGroupsWithWindow.join(', ')}`;
      }
      return groups.length > 1 ? 'окно у групп' : 'окно у группы';
    }
    if (cell.windowStatus === 'teacher-window') return 'окно у преподавателя';
    if (cell.windowStatus === 'both-window') {
      if (cell.freeGroupsWithWindow && cell.freeGroupsWithWindow.length > 0 && cell.freeGroups.length > 1) {
        return `окно и у преподавателя, и у ${cell.freeGroupsWithWindow.join(', ')}`;
      }
      return groups.length > 1 ? 'окно и у преподавателя, и у групп' : 'окно и у преподавателя, и у группы';
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
  <title>{page === 'home' ? 'Запара — планирование для преподавателей' : page === 'consultations' ? 'Консультации — Запара' : `${sections.find((section) => section.page === page)?.name} — Запара`}</title>
</svelte:head>

<div class="site-shell">
  <header class="topbar">
    <button class="brand" type="button" on:click={() => go('home')} aria-label="На главную">
      <span class="brand-mark"><span></span><span></span><span></span><span></span></span>
      <span class="brand-copy"><strong>Запара</strong><small>планирование времени</small></span>
    </button>
    <nav aria-label="Основная навигация">
      <button type="button" class:nav-current={page === 'home'} on:click={() => go('home')}>Главная</button>
      <button type="button" class:nav-current={page === 'retakes'} on:click={() => go('retakes')}>Пересдачи</button>
      <button type="button" class:nav-current={page === 'consultations'} on:click={() => go('consultations')}>Консультации</button>
      <button type="button" class:nav-current={page === 'substitutions'} on:click={() => go('substitutions')}>Замены</button>
      <button type="button" class:nav-current={page === 'meetings'} on:click={() => go('meetings')}>Встречи</button>
      <button type="button" class:nav-current={page === 'schedule'} on:click={() => go('schedule')}>Расписание</button>
    </nav>
    <span class="topbar-note">Расписание ОмГТУ <span class="online-dot"></span></span>
  </header>

  <main>
    {#if page === 'home'}
      <section class="hero">
        <div class="hero-copy">
          <div class="eyebrow"><span class="eyebrow-line"></span> Инструмент преподавателя · ОмГТУ</div>
          <h1>Меньше времени<br />на <em>поиск времени.</em></h1>
          <p>Планируйте консультации, пересдачи, замены и встречи на основе актуального расписания. Выберите задачу — свободные окна найдём вместе.</p>
          <button type="button" class="primary-button hero-button" on:click={() => go('consultations')}>Найти время для консультации <span aria-hidden="true">↗</span></button>
          <div class="hero-footnote"><span class="mini-line"></span> Данные напрямую из расписания университета</div>
        </div>
        <div class="hero-visual" aria-hidden="true">
          <div class="visual-label">НЕДЕЛЯ / ОБЗОР</div>
          <div class="visual-header"><span>ПН</span><span>ВТ</span><span>СР</span><span>ЧТ</span><span>ПТ</span></div>
          <div class="visual-grid">
            {#each Array(25) as _, index}
              <span class:visual-open={[1, 3, 7, 8, 11, 13, 16, 17, 20, 23].includes(index)} class:visual-chosen={[7, 13, 17].includes(index)}></span>
            {/each}
          </div>
          <div class="visual-bottom"><span class="visual-ring">✓</span><span>Общие свободные окна<br /><strong>найдены</strong></span><span class="visual-arrow">↗</span></div>
          <div class="visual-accent"></div>
        </div>
      </section>

      <section class="section-picker">
        <div class="section-heading"><div><span class="section-kicker">ВАШИ ЗАДАЧИ</span><h2>С чего начнём?</h2></div><p>Один инструмент для разных задач в расписании.</p></div>
        <div class="section-grid">
          {#each sections as section}
            <button type="button" class="section-card" class:card-active={section.active} on:click={() => go(section.page)}>
              <span class="card-top"><span>{section.number} / 04</span><span class="card-symbol">{section.icon}</span></span>
              <span class="card-title">{section.name}</span>
              <span class="card-description">{section.description}</span>
              <span class="card-bottom"><span class:available={section.active}>{section.active ? 'Доступно сейчас' : 'В разработке'}</span><span class="card-arrow">↗</span></span>
            </button>
          {/each}
        </div>
      </section>
    {:else if page === 'consultations' || page === 'retakes' || page === 'substitutions' || page === 'meetings'}
      <div class="workspace">
        <div class="breadcrumb"><button type="button" on:click={() => go('home')}>Главная</button><span>/</span><span>{page === 'retakes' ? 'Пересдачи' : page === 'substitutions' ? 'Замены' : page === 'meetings' ? 'Рабочие встречи' : 'Консультации'}</span></div>
        <section class="workspace-heading"><div><span class="section-kicker">ПЛАНИРОВАНИЕ / {page === 'retakes' ? '01' : page === 'substitutions' ? '03' : page === 'meetings' ? '04' : '02'}</span><h1>{page === 'retakes' ? 'Время для пересдачи' : page === 'substitutions' ? 'Замены занятий' : page === 'meetings' ? 'Рабочие встречи' : 'Время для консультации'}<span class="heading-period">.</span></h1><p>{page === 'retakes' ? 'Найдём общий свободный слот для преподавателей и учебных групп.' : page === 'substitutions' ? 'Покажем занятия преподавателя и коллег, которые могут его заменить.' : page === 'meetings' ? 'Сопоставим расписания коллег и найдём время, когда свободны все.' : 'Сопоставим расписание преподавателя и групп, чтобы найти удобные окна.'}</p></div><div class="heading-decoration" aria-hidden="true">{page === 'retakes' ? '↗' : page === 'substitutions' ? '⇄' : page === 'meetings' ? '✧' : '◷'}</div></section>

        {#if page === 'retakes'}<div class="retake-mode"><div><span class="section-kicker">ФОРМАТ</span><strong>Тип пересдачи</strong></div><div class="retake-toggle" role="group" aria-label="Тип пересдачи"><button type="button" class:active={retakeMode === 'first'} aria-pressed={retakeMode === 'first'} on:click={() => changeRetakeMode('first')}>1 пересдача</button><button type="button" class:active={retakeMode === 'commission'} aria-pressed={retakeMode === 'commission'} on:click={() => changeRetakeMode('commission')}>Комиссионная пересдача</button></div></div>{/if}

        <div class="workspace-layout">
          <aside class="controls-panel">
            <div class="panel-top"><span class="panel-number">01 — НАСТРОЙКА</span><h2>{page === 'substitutions' ? 'Кого и когда заменить?' : 'Кого и когда собрать?'}</h2></div>
            {#if page === 'meetings'}
              <div class="field-block"><div class="field-head"><label>Преподаватели</label><span>01</span></div>
                <SearchField type="person" placeholder="Добавить преподавателя" onPick={addMeetingTeacher} />
                {#if meetingTeachers.length}<div class="group-chips">{#each meetingTeachers as person (person.id)}<span class="group-chip">{person.label}<button type="button" on:click={() => removeMeetingTeacher(person.id)} aria-label={`Удалить преподавателя ${person.label}`}>×</button></span>{/each}</div>{/if}
                {#if meetingError}<p class="form-error">{meetingError}</p>{:else}<p class="field-hint">Можно добавить любое количество преподавателей.</p>{/if}
              </div>
            {:else}<div class="field-block"><div class="field-head"><label>{page === 'substitutions' ? 'Кого нужно заменить' : 'Преподаватель'}</label><span>01</span></div>
              {#if teacher}
                <div class="chosen-person"><span class="avatar">{teacher.label.slice(0, 1)}</span><span><strong>{teacher.label}</strong><small>Преподаватель выбран</small></span><button type="button" on:click={removeTeacher} aria-label="Удалить преподавателя">×</button></div>
              {:else}
                <SearchField type="person" placeholder="Начните вводить ФИО" onPick={chooseTeacher} />
                <p class="field-hint">Подсказки появятся после 4 символов</p>
              {/if}
            </div>{/if}

            {#if page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')}
              <div class="field-block"><div class="field-head"><label>{page === 'substitutions' ? 'Кто может заменить' : 'Состав комиссии'}</label><span>02</span></div>
                <div class="commission-choice" role="group" aria-label={page === 'substitutions' ? 'Способ выбора замещающих преподавателей' : 'Способ выбора комиссии'}><button type="button" class:active={commissionChoice === 'people'} aria-pressed={commissionChoice === 'people'} on:click={() => changeCommissionChoice('people')}>Конкретные люди</button><button type="button" class:active={commissionChoice === 'group'} aria-pressed={commissionChoice === 'group'} on:click={() => changeCommissionChoice('group')}>Тематическая группа</button></div>
                {#if commissionChoice === 'people'}
                  {#if page === 'substitutions' || commissionTeachers.length < 2}<SearchField type="person" placeholder="Добавить преподавателя" onPick={addCommissionTeacher} />{/if}
                  {#if commissionTeachers.length}<div class="group-chips">{#each commissionTeachers as person (person.id)}<span class="group-chip">{person.label}<button type="button" on:click={() => removeCommissionTeacher(person.id)} aria-label={`Удалить преподавателя ${person.label}`}>×</button></span>{/each}</div>{/if}
                  {#if committeeError}<p class="form-error">{committeeError}</p>{:else}<p class="field-hint">{page === 'substitutions' ? 'Можно добавить любое количество преподавателей.' : 'Добавьте одного или двух преподавателей.'}</p>{/if}
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
                  {#if selectedCommissionGroup}<p class="field-hint">Кандидатов: {selectedCommissionGroup.people.filter((person) => person.id !== teacher?.id).length}. {page === 'substitutions' ? 'Заменяемый преподаватель' : 'Основной преподаватель'} в число кандидатов не входит.</p>{/if}
                {/if}
              </div>
              <div class="mercy-field"><label class="mercy-switch"><input type="checkbox" checked={mercy} on:change={(event) => changeMercy((event.currentTarget as HTMLInputElement).checked)} /><span class="mercy-track"></span><strong>Милосердие</strong></label><p>Не считать доступными преподавателей, у которых в этот день совсем нет пар.</p></div>
            {/if}

            {#if page !== 'substitutions' && page !== 'meetings'}<div class="field-block"><div class="field-head"><label>Учебные группы</label><span>{groupsStepNumber}</span></div>
              <SearchField type="group" placeholder="Например, М-251" onPick={addGroup} />
              {#if groups.length}<div class="group-chips">{#each groups as group (group.id)}<span class="group-chip">{group.label}<button type="button" on:click={() => removeGroup(group.id)} aria-label={`Удалить группу ${group.label}`}>×</button></span>{/each}</div>{:else}<p class="field-hint">Можно добавить любое количество групп</p>{/if}
            </div>{/if}

            {#if page !== 'substitutions' && page !== 'meetings'}
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
                      <button type="button" on:click={() => removeAuditorium(aud.id)} aria-label={`Удалить аудиторию ${aud.label}`}>×</button>
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
                                {isAdded ? '✓ ' : '+ '}{aud.name || aud.number}
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
            <button class="primary-button generate-button" type="button" disabled={(page === 'meetings' ? !meetingTeachers.length : !teacher) || (page !== 'meetings' && page !== 'substitutions' && !groups.length) || !start || !finish || start > finish || loading || ((page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && (commissionChoice === 'people' ? !commissionTeachers.length : !commissionGroupId))} on:click={generate}>{loading ? 'Загружаем расписание…' : page === 'substitutions' ? 'Показать замены' : 'Показать свободное время'}<span aria-hidden="true">↗</span></button>
            <div class="panel-note"><span>ⓘ</span><p>{page === 'substitutions' ? 'Выбирайте занятия заменяемого преподавателя. Доступность коллег показана под каждой парой и не ограничивает выбор.' : page === 'meetings' ? 'Зелёные слоты свободны у всех выбранных преподавателей.' : 'Расписание загружается с сайта ОмГТУ. В таблице можно выбрать подходящие пары.'}</p></div>
          </aside>

          <section class="results-panel" aria-live="polite">
            <div class="results-header">
              <div>
                <span class="panel-number">02 — РЕЗУЛЬТАТ</span>
                <h2>{page === 'substitutions' ? 'Занятия и доступные замены' : 'Общие свободные окна'}</h2>
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
            {#if error}<div class="state-card error-card"><span class="state-icon">!</span><h3>Не удалось получить расписание</h3><p>{error}</p><button type="button" on:click={generate}>Повторить запрос ↗</button></div>
            {:else if loading}<div class="state-card"><span class="state-icon loading-icon">◷</span><h3>Сопоставляем расписания</h3><p>{page === 'substitutions' ? 'Загружаем занятия и расписания возможных замещающих преподавателей.' : page === 'meetings' ? 'Загружаем расписания выбранных преподавателей.' : 'Загружаем основного преподавателя, группы и выбранный состав комиссии.'}</p></div>
            {:else if !hasGenerated}<div class="state-card empty-card"><div class="empty-illustration"><span>01</span><span>02</span><span>03</span><span>04</span></div><h3>{page === 'substitutions' ? 'Здесь появятся занятия' : 'Здесь появятся свободные окна'}</h3><p>{page === 'substitutions' ? 'Выберите преподавателя, которого нужно заменить, укажите возможных заменяющих и период. Мы покажем его занятия и доступность коллег.' : page === 'meetings' ? 'Добавьте преподавателей и укажите даты. Мы покажем пары, свободные у всех выбранных.' : `Выберите преподавателя, добавьте группы и укажите даты.${page === 'retakes' && retakeMode === 'commission' ? ' Для комиссии укажите людей или тематическую группу.' : ''} Мы покажем общие свободные пары по неделям.`}</p></div>
            {:else}
              <div class="legend">
                {#if page === 'substitutions'}
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
              {#if failedCommissionCount > 0}<p class="warning-note">Не удалось загрузить расписание {failedCommissionCount} {failedCommissionCount === 1 ? 'преподавателя' : 'преподавателей'} {page === 'substitutions' ? 'для замены' : page === 'meetings' ? 'для встречи' : 'комиссии'}. {page === 'meetings' ? 'Общие свободные слоты нельзя определить, пока не загрузятся все расписания.' : 'Они не отмечены как доступные.'}</p>{/if}
              {#each weeks as week, index}
                <div class="week-block"><div class="week-title"><div><span>НЕДЕЛЯ {String(index + 1).padStart(2, '0')}</span><h3>{dateShort(week.monday)} — {dateShort(week.saturday)}</h3></div><span>ПН — СБ</span></div>
                  <div class="table-scroll"><div class="schedule-table" role="table" aria-label={`Неделя ${dateShort(week.monday)} — ${dateShort(week.saturday)}`}>
                    <div class="table-row table-head" role="row"><div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>{#each week.dates as date, day}{@const dStatus = week.daysStatus ? week.daysStatus[day] : null}<div role="columnheader" class:col-teacher-free={displayMode === 'windows' && dStatus && dStatus.teacherFreeDay && !dStatus.bothFreeDay} class:col-group-free={displayMode === 'windows' && dStatus && dStatus.groupFreeDay && !dStatus.bothFreeDay} class:col-both-free={displayMode === 'windows' && dStatus && dStatus.bothFreeDay} title={displayMode === 'windows' ? (dStatus?.tooltipText || '') : ''}>{#if displayMode === 'windows'}<div class="head-day-info"><strong>{dayNames[day]}</strong><span>{dateShort(date)}</span></div>{#if dStatus && dStatus.bothFreeDay}<span class="day-col-badge" class:badge-no-lessons={page === 'meetings'} class:badge-both={page !== 'meetings'}>{dStatus.badgeLabel || (groups.length > 1 ? 'Без пар у всех' : 'Без пар у обоих')}</span>{:else if dStatus && dStatus.teacherFreeDay}<span class="day-col-badge badge-teacher">{dStatus.badgeLabel || 'Без пар у преп.'}</span>{:else if dStatus && dStatus.groupFreeDay}<span class="day-col-badge badge-group">{dStatus.badgeLabel || (groups.length > 1 ? 'Без пар у групп' : 'Без пар у группы')}</span>{/if}{:else}<strong>{dayNames[day]}</strong><span>{dateShort(date)}</span>{/if}</div>{/each}</div>
                    {#each week.rows as row, rowIndex}<div class="table-row" role="row"><div class="slot-label" role="rowheader"><strong>{String(row.slot.number).padStart(2, '0')}</strong><span>{row.slot.start}<br />{row.slot.end}</span></div>
                      {#each row.cells as cell, day}{@const dStatus = week.daysStatus ? week.daysStatus[day] : null}<div role="cell" class="cell-wrap" class:col-teacher-free={displayMode === 'windows' && dStatus && dStatus.teacherFreeDay && !dStatus.bothFreeDay} class:col-group-free={displayMode === 'windows' && dStatus && dStatus.groupFreeDay && !dStatus.bothFreeDay} class:col-both-free={displayMode === 'windows' && dStatus && dStatus.bothFreeDay} class:col-last-row={displayMode === 'windows' && rowIndex === week.rows.length - 1}><button type="button" class="slot-cell" class:mode-classic={displayMode === 'classic'} class:is-free={cell.available} class:is-selected={selected.has(cell.key)} class:window-none={displayMode === 'windows' && cell.available && cell.windowStatus === 'none'} class:window-group={displayMode === 'windows' && cell.available && cell.windowStatus === 'group-window'} class:window-teacher={displayMode === 'windows' && cell.available && cell.windowStatus === 'teacher-window'} class:window-both={displayMode === 'windows' && cell.available && cell.windowStatus === 'both-window'} class:show-candidates={(page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && commissionChoice === 'group' && selected.has(cell.key)} disabled={!cell.available} aria-pressed={cell.available ? selected.has(cell.key) : undefined} aria-label={cellAriaLabel(cell, row.slot)} on:mouseenter={(e) => { if (displayMode === 'windows') showTooltip(cell, row.slot, e); }} on:mouseleave={hideTooltip} on:focus={(e) => { if (displayMode === 'windows') showTooltip(cell, row.slot, e); }} on:blur={hideTooltip} on:click={() => toggle(cell)}>
                        {#if selected.has(cell.key) && slotAssignedAuditoriums.has(cell.key)}<span class="cell-assigned-aud-chip">Ауд. {slotAssignedAuditoriums.get(cell.key)?.name}</span>{/if}
                        {#if cell.outOfRange}<span class="cell-muted">Вне периода</span>{:else if displayMode === 'classic'}{#if page === 'meetings'}{#if cell.available}<span class="cell-group-list">Свободны все</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else}<span class="cell-muted">Занято</span>{/if}{:else if page === 'substitutions'}{#if cell.teacherBusy}<span class="cell-group-list lesson-summary">{cell.lessons.join('; ')}</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else}<span class="cell-muted">Нет занятия</span>{/if}{:else if cell.teacherBusy}<span class="cell-muted">Занято</span>{:else if !cell.freeGroups.length}<span class="cell-muted">Нет групп</span>{:else}<span class="cell-group-list">{cell.freeGroups.map((group) => group.label).join(', ')}</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{/if}{:else}{#if !cell.available}<span class="cell-muted cell-unavailable-reason">{cell.unavailableText ?? 'Занято'}</span>{:else if page === 'meetings'}<div class="cell-free-body">{#if cell.teachersDetails && cell.teachersDetails.length > 0}<div class="cell-chips-wrap">{#each cell.teachersDetails as t}<span class="mini-chip" class:chip-free={t.available && !t.hasWindow} class:chip-teacher-window={t.available && t.hasWindow} class:chip-no-lessons={t.noLessons} class:chip-busy={!t.available && !t.noLessons} title={t.person.label}><span class="mini-chip-label">{t.person.label.split(' ')[0]}</span></span>{/each}</div>{:else}<span class="cell-group-list">Свободно</span>{/if}<span class="cell-status-tag tag-{cell.windowStatus}">{windowStatusShort(cell.windowStatus)}</span></div><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else if page === 'substitutions'}<div class="cell-free-body"><span class="cell-group-list lesson-summary">{cell.lessons.join('; ')}</span></div><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else}<div class="cell-free-body">{#if cell.groupsDetails && cell.groupsDetails.length > 1}<div class="cell-chips-wrap">{#each cell.groupsDetails as detail}<span class="mini-chip" class:chip-free={!detail.busy && !detail.hasWindow} class:chip-group-window={!detail.busy && detail.hasWindow} class:chip-busy={detail.busy} title={detail.group.label}><span class="mini-chip-label">{detail.group.label}</span></span>{/each}</div>{:else}<span class="cell-group-list">{cell.freeGroups.map((group) => group.label).join(', ')}</span>{/if}<span class="cell-status-tag tag-{cell.windowStatus}">{windowStatusShort(cell.windowStatus)}</span></div><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{/if}{/if}
                        {#if (page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && commissionChoice === 'group' && selected.has(cell.key)}<span class="selected-commission-names"><span class="candidate-list-label">{page === 'substitutions' ? 'Могут заменить:' : 'Комиссия:'}</span>{#if freeCommission(cell).length}{#each freeCommission(cell) as name}<span class="candidate-name">{name}</span>{/each}{:else}<span class="candidate-name">Никого из группы</span>{/if}</span>{/if}
                      </button>
                      {#if (page === 'substitutions' ? cell.teacherBusy : page === 'retakes' && retakeMode === 'commission' && !cell.outOfRange)}<div class="commission-strip">
                        {#if commissionChoice === 'people'}
                          {#each cell.commission as entry, number}<span class="commission-person-indicator" class:can-attend={entry.available} class:no-lessons={entry.reason === 'no-lessons'} class:load-error={entry.reason === 'load-error'} title={`${entry.person.label}: ${commissionReason(entry.reason)}`} aria-label={`Преподаватель ${number + 1}, ${entry.person.label}: ${commissionReason(entry.reason)}`}>{number + 1} {entry.available ? '✓' : '×'}</span>{/each}
                        {:else}
                          <span class="commission-count" title={freeCommission(cell).length ? freeCommission(cell).join('\n') : 'Нет доступных преподавателей'} aria-label={`${freeCommission(cell).length} из ${cell.commission.length} преподавателей ${page === 'substitutions' ? 'могут заменить' : 'комиссии могут присутствовать'}`}>{freeCommission(cell).length} из {cell.commission.length} могут</span>
                        {/if}
                      </div>{/if}
                      </div>{/each}
                    </div>{/each}
                  </div></div>
                </div>
              {/each}
              {#if !weeks.some((week) => week.rows.some((row) => row.cells.some((cell) => cell.available)))}<p class="no-free">{page === 'substitutions' ? 'В этом периоде занятий для замены не найдено. Попробуйте изменить даты.' : page === 'meetings' ? 'В этом периоде общих свободных пар не найдено. Попробуйте изменить даты или состав участников.' : 'В этом периоде общих свободных пар не найдено. Попробуйте изменить даты или состав групп.'}</p>{/if}
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
              <strong>Выбрано {page === 'substitutions' ? 'занятий' : 'слотов'}</strong>
              <small>{selectedCount ? `В ${new Set(selectedDetails.map((item) => item.cell.date)).size} дн. · Посмотреть` : page === 'substitutions' ? 'Нажмите на занятие' : 'Нажмите на свободную пару'}</small>
            </span>
            {#if selectedCount}
              <span class="selection-arrow-icon">↗</span>
            {/if}
          </button>
          {#if selectedCount && page !== 'meetings'}
            <div class="selection-actions">
              <button type="button" class="btn-aud-finder" on:click={() => openAuditoriumModal('all')}>
                <span>Подобрать аудиторию</span>
                <span class="btn-arrow">↗</span>
              </button>
              <button type="button" class="btn-clear-selection" on:click={clearSelection}>Очистить</button>
            </div>
          {/if}
        </div>
      {/if}
    {:else if page === 'schedule'}
      <div class="workspace workspace-fluid">
        <div class="breadcrumb">
          <button type="button" on:click={() => go('home')}>Главная</button>
          <span>/</span>
          <span>Расписание</span>
        </div>
        <section class="workspace-heading">
          <div>
            <span class="section-kicker">ПРОСМОТР / 05</span>
            <h1>Сравнение расписания<span class="heading-period">.</span></h1>
            <p>Просматривайте и сравнивайте расписание групп, преподавателей и аудиторий в едином календаре.</p>
          </div>
          <div class="heading-decoration" aria-hidden="true">▦</div>
        </section>

        <div class="workspace-layout viewer-layout">
          <aside class="controls-panel">
            <div class="panel-top">
              <span class="panel-number">01 — ВЫБОР ОБЪЕКТОВ</span>
              <h2>Кого и что сравнить?</h2>
            </div>

            <div class="field-block">
              <div class="field-head">
                <label>Добавить в расписание</label>
                <span>01</span>
              </div>
              <div class="commission-choice" role="group" aria-label="Тип объекта">
                <button
                  type="button"
                  class:active={viewerActiveType === 'group'}
                  aria-pressed={viewerActiveType === 'group'}
                  on:click={() => (viewerActiveType = 'group')}
                >
                  Группа
                </button>
                <button
                  type="button"
                  class:active={viewerActiveType === 'person'}
                  aria-pressed={viewerActiveType === 'person'}
                  on:click={() => (viewerActiveType = 'person')}
                >
                  Преподаватель
                </button>
                <button
                  type="button"
                  class:active={viewerActiveType === 'auditorium'}
                  aria-pressed={viewerActiveType === 'auditorium'}
                  on:click={() => (viewerActiveType = 'auditorium')}
                >
                  Аудитория
                </button>
              </div>

              {#if viewerActiveType === 'group'}
                <SearchField
                  type="group"
                  placeholder="Например, ФИТ-211 или М-251"
                  onPick={(item) => addScheduleViewerEntity(item, 'group')}
                />
              {:else if viewerActiveType === 'person'}
                <SearchField
                  type="person"
                  placeholder="Начните вводить ФИО преподавателя"
                  onPick={(item) => addScheduleViewerEntity(item, 'person')}
                />
              {:else}
                <SearchField
                  type="auditorium"
                  placeholder="Номер или название, напр. 6-308"
                  onPick={(item) => addScheduleViewerEntity(item, 'auditorium')}
                />
              {/if}

              {#if viewerEntities.length}
                <div class="group-chips">
                  {#each viewerEntities as entity (entity.id + entity.type)}
                    <span class="group-chip">
                      {entity.type === 'auditorium' ? `Ауд. ${entity.label}` : entity.type === 'person' ? `Преп. ${entity.label}` : entity.label}
                      <button
                        type="button"
                        on:click={() => removeScheduleViewerEntity(entity.id, entity.type)}
                        aria-label={`Удалить ${entity.label}`}
                      >×</button>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="field-hint">Добавьте группы, преподавателей или аудитории для совместного просмотра</p>
              {/if}
            </div>

            <div class="field-block date-block">
              <div class="field-head">
                <label>Период</label>
                <span>02</span>
              </div>
              <div class="date-fields">
                <div>
                  <label for="viewer-start-date">С</label>
                  <input
                    id="viewer-start-date"
                    type="date"
                    bind:value={viewerStart}
                    on:change={() => {
                      if (viewerHasGenerated) void generateScheduleView();
                    }}
                  />
                </div>
                <div>
                  <label for="viewer-end-date">ПО</label>
                  <input
                    id="viewer-end-date"
                    type="date"
                    min={viewerStart}
                    bind:value={viewerFinish}
                    on:change={() => {
                      if (viewerHasGenerated) void generateScheduleView();
                    }}
                  />
                </div>
              </div>
            </div>
            {#if viewerStart && viewerFinish && viewerStart > viewerFinish}
              <p class="form-error">Дата окончания раньше даты начала.</p>
            {/if}

            <button
              class="primary-button generate-button"
              type="button"
              disabled={viewerLoading || viewerEntities.length === 0 || viewerStart > viewerFinish}
              on:click={generateScheduleView}
            >{viewerLoading ? 'Загружаем расписание…' : 'Показать расписание'}<span aria-hidden="true">↗</span></button>

            <div class="panel-note">
              <span>ⓘ</span>
              <p>Каждая ячейка календаря разделена по горизонтали на строки для каждого выбранного участника.</p>
            </div>
          </aside>

          <section class="results-panel viewer-results" aria-live="polite">
            <div class="results-header">
              <div>
                <span class="panel-number">02 — РЕЗУЛЬТАТ</span>
                <h2>Сравнительное расписание</h2>
              </div>
              {#if viewerHasGenerated}
                <span class="week-count">{viewerWeeks.length} {viewerWeeks.length === 1 ? 'неделя' : viewerWeeks.length < 5 ? 'недели' : 'недель'}</span>
              {/if}
            </div>

            {#if viewerError}
              <div class="state-card error-card">
                <span class="state-icon">!</span>
                <h3>Не удалось получить расписание</h3>
                <p>{viewerError}</p>
                <button type="button" on:click={generateScheduleView}>Повторить запрос ↗</button>
              </div>
            {:else if viewerLoading}
              <div class="state-card">
                <span class="state-icon loading-icon">◷</span>
                <h3>Сопоставляем расписания</h3>
                <p>Загружаем данные для выбранных групп, преподавателей и аудиторий из расписания ОмГТУ...</p>
              </div>
            {:else if !viewerHasGenerated}
              <div class="state-card empty-card">
                <div class="empty-illustration">
                  <span>01</span>
                  <span>02</span>
                  <span>03</span>
                  <span>04</span>
                </div>
                <h3>Здесь появится расписание</h3>
                <p>Выберите участников или аудитории, укажите даты и нажмите «Показать расписание».</p>
              </div>
            {:else}
              <div class="legend">
                <span><i class="legend-dot free"></i>Свободно</span>
                <span><i class="legend-dot selected"></i>Занятие</span>
                <span>Подробности о паре — при наведении</span>
              </div>

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
                          <div role="columnheader">
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
                            <div role="cell" class="cell-wrap viewer-cell-wrap" class:out-of-range={cell.outOfRange}>
                              {#if cell.outOfRange}
                                <div class="slot-cell out-of-range">
                                  <span class="cell-muted">Вне периода</span>
                                </div>
                              {:else}
                                <div class="viewer-lines-stack">
                                  {#each cell.lanes as lane (lane.entity.id + lane.entity.type)}
                                    <div
                                      class="viewer-entity-line"
                                      class:line-free={lane.isFree}
                                      class:line-busy={!lane.isFree}
                                    >
                                      {#if viewerEntities.length > 1}
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
                                              tabindex="0"
                                              role="button"
                                              on:mouseenter={(e) => showViewerTooltip(lesson, lane.entity, row.slot, cell.date, e)}
                                              on:mouseleave={hideViewerTooltip}
                                              on:focus={(e) => showViewerTooltip(lesson, lane.entity, row.slot, cell.date, e)}
                                              on:blur={hideViewerTooltip}
                                            >
                                              {#if lesson.kindOfWork}
                                                <span class="viewer-kind-prefix">{formatLessonKindShort(lesson.kindOfWork)}</span>
                                              {/if}
                                              <strong class="viewer-lesson-title" title={lesson.discipline}>{lesson.discipline}</strong>
                                              <span class="viewer-lesson-details">
                                                {#if lesson.subgroup}
                                                  <span class="viewer-subgroup-info">п. {lesson.subgroup}</span>
                                                {/if}
                                                {#if lane.entity.type === 'group'}
                                                  {#if lesson.auditorium}
                                                    <span class="viewer-aud-info">ауд. {lesson.auditorium}</span>
                                                  {/if}
                                                  {#if lesson.lecturer}
                                                    <span class="viewer-person-info" title={lesson.lecturer}>{lesson.lecturer}</span>
                                                  {/if}
                                                {:else if lane.entity.type === 'person'}
                                                  {#if lesson.auditorium}
                                                    <span class="viewer-aud-info">ауд. {lesson.auditorium}</span>
                                                  {/if}
                                                  {#if lesson.group}
                                                    <span class="viewer-person-info" title={lesson.group}>{lesson.group}</span>
                                                  {/if}
                                                {:else}
                                                  {#if lesson.group}
                                                    <span class="viewer-person-info" title={lesson.group}>{lesson.group}</span>
                                                  {/if}
                                                  {#if lesson.lecturer}
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
          </section>
        </div>
      </div>
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
        <span class="tooltip-badge status-{cell.available ? (selected.has(cell.key) ? 'selected' : cell.windowStatus) : 'unavailable'}">
          {#if cell.outOfRange}
            Вне периода
          {:else if !cell.available}
            {cell.unavailableText ?? 'Занято'}
          {:else if selected.has(cell.key)}
            Выбрано
          {:else if cell.windowStatus === 'both-window'}
            {page === 'meetings' ? 'Окно у всех' : (groups.length > 1 ? 'Окно и у преподавателя, и у групп' : 'Окно и у преподавателя, и у группы')}
          {:else}
            {windowStatusShort(cell.windowStatus)}
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
                  <div class="tooltip-entity-card" class:card-free={t.available && !t.hasWindow && !t.noLessons} class:card-teacher-window={t.available && t.hasWindow && !t.noLessons} class:card-no-lessons={t.noLessons} class:card-busy={!t.available && !t.noLessons}>
                    <div class="entity-head">
                      <strong class="entity-title">{t.person.label}</strong>
                      <span class="entity-badge">{t.noLessons ? 'нет пар' : !t.available ? 'занят' : t.hasWindow ? 'окно' : 'без окон'}</span>
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
                        <span>Свободен (окно перед этой парой)</span>
                      {:else}
                        <span>Свободен (пара без окон)</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        {:else if page === 'substitutions'}
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
            <div class="tooltip-entity-card" class:card-free={!cell.teacherBusy && !cell.teacherHasWindow} class:card-teacher-window={!cell.teacherBusy && cell.teacherHasWindow} class:card-busy={cell.teacherBusy}>
              <div class="entity-head">
                <strong class="entity-title">{teacher ? teacher.label : 'Преподаватель'}</strong>
                <span class="entity-badge">{cell.teacherBusy ? 'занят' : cell.teacherHasWindow ? 'окно' : 'без окон'}</span>
              </div>
              <div class="entity-desc">
                {#if cell.teacherBusy}
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
                  <span>Свободен (окно перед этой парой)</span>
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
                  <div class="tooltip-entity-card" class:card-free={!detail.busy && !detail.hasWindow} class:card-group-window={!detail.busy && detail.hasWindow} class:card-busy={detail.busy}>
                    <div class="entity-head">
                      <strong class="entity-title">{detail.group.label}</strong>
                      <span class="entity-badge">{detail.busy ? 'занята' : detail.hasWindow ? 'окно' : 'без окон'}</span>
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
                      {:else if detail.hasWindow}
                        <span>Свободна (окно перед этой парой)</span>
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
            <div class="entity-head">
              <strong class="entity-title">{lesson.discipline}</strong>
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
          <button type="button" class="modal-close-button" on:click={closeAuditoriumModal} aria-label="Закрыть">✕</button>
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
                      <button type="button" class="btn-aud-pick added" on:click={() => removeAuditorium(String(aud.auditoriumOid))}>Добавлена ×</button>
                    {:else}
                      <button type="button" class="btn-aud-pick" on:click={() => pickAuditoriumFromModal(aud)}>Выбрать ↗</button>
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
          <button type="button" class="modal-close-button" on:click={closeSelectedSlotsModal} aria-label="Закрыть">✕</button>
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
                            {windowStatusShort(item.cell.windowStatus)}
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
                            >×</button>
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
                      {slotAssignedAuditoriums.has(item.cell.key) ? 'Сменить аудиторию ↗' : 'Подобрать аудиторию ↗'}
                    </button>
                    <button
                      type="button"
                      class="btn-slot-remove"
                      on:click={() => removeSelectedSlot(item.cell.key)}
                      aria-label="Удалить пару из выбранных"
                      title="Убрать"
                    >
                      ✕
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
              Подобрать на все пары ↗
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
