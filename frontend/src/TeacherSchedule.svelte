<script lang="ts">
  import PlannerPageFrame from './PlannerPageFrame.svelte';
  import PlannerFilterBar from './PlannerFilterBar.svelte';
  import PlannerToolbar from './PlannerToolbar.svelte';
  import SearchField from './SearchField.svelte';
  import { addDays, buildViewerWeeks, formatDate, getPlannedEvents, getSchedule, mergePlannedEvents, toIso, type SearchItem, type ViewerWeek } from './lib/schedule';
  import { createEventDispatcher, onMount } from 'svelte';

  const dispatch = createEventDispatcher<{ home: void }>();
  const today = new Date();
  const monday = addDays(today, -((today.getDay() + 6) % 7));
  let currentDate = toIso(today);
  onMount(() => {
    const timer = window.setInterval(() => { currentDate = toIso(new Date()); }, 60_000);
    return () => { window.clearInterval(timer); if (loadTimer !== null) window.clearTimeout(loadTimer); };
  });
  const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  let teacher: SearchItem | null = null;
  let start = toIso(monday);
  let finish = toIso(addDays(monday, 12));
  let weeks: ViewerWeek[] = [];
  let loading = false;
  let error = '';
  let loaded = false;
  let requestId = 0;
  let loadTimer: number | null = null;

  function queueLoad() {
    if (loadTimer !== null) window.clearTimeout(loadTimer);
    loadTimer = window.setTimeout(() => {
      loadTimer = null;
      if (teacher && start && finish && start <= finish) void load();
    }, 250);
  }

  function selectTeacher(person: SearchItem) {
    requestId++;
    loading = false;
    teacher = person;
    weeks = [];
    loaded = false;
    error = '';
    queueLoad();
  }

  function clearTeacher() {
    requestId++;
    teacher = null;
    weeks = [];
    loading = false;
    loaded = false;
    error = '';
    if (loadTimer !== null) window.clearTimeout(loadTimer);
    loadTimer = null;
  }

  async function load() {
    if (!teacher || !start || !finish || start > finish) return;
    const id = ++requestId;
    const selected = teacher;
    const requestedStart = start;
    const requestedFinish = finish;
    loading = true;
    loaded = false;
    error = '';
    try {
      const [events, planned] = await Promise.all([
        getSchedule('person', selected.id, requestedStart, requestedFinish),
        getPlannedEvents(requestedStart, requestedFinish).catch(() => [])
      ]);
      if (id !== requestId) return;
      const mergedEvents = mergePlannedEvents(events, planned, 'person', selected.id);
      const entity = { id: selected.id, label: selected.label, type: 'person' as const };
      weeks = buildViewerWeeks(requestedStart, requestedFinish, [entity], new Map([[`person:${selected.id}`, mergedEvents]]));
      loaded = true;
    } catch (cause) {
      if (id === requestId) error = cause instanceof Error ? cause.message : 'Не удалось получить расписание.';
    } finally {
      if (id === requestId) loading = false;
    }
  }

  function dateShort(value: string) { return formatDate(value, { day: '2-digit', month: '2-digit' }); }
  function changePeriod() { requestId++; loading = false; loaded = false; weeks = []; error = ''; queueLoad(); }
</script>

<PlannerPageFrame section="ПРОСМОТР" sectionNumber="02" breadcrumb="Преподаватели" title="Расписание преподавателей" description="Выберите преподавателя и посмотрите его занятия на нужные даты." on:home={() => dispatch('home')}>
  <PlannerFilterBar slot="filters" ariaLabel="Фильтры расписания преподавателя" className="teacher-schedule-controls">
    <div class="teacher-picker"><span class="teacher-picker-label">Преподаватель</span>{#if teacher}<div class="teacher-picked"><div><strong>{teacher.label}</strong>{#if teacher.description}<small>{teacher.description}</small>{/if}</div><button type="button" on:click={clearTeacher} aria-label="Выбрать другого преподавателя">Изменить</button></div>{:else}<SearchField type="person" placeholder="Найти преподавателя по имени" onPick={selectTeacher} />{/if}</div>
    <div class="sub-filter"><label for="teacher-start">Период с</label><input id="teacher-start" type="date" bind:value={start} on:change={changePeriod} /></div>
    <div class="sub-filter"><label for="teacher-finish">по</label><input id="teacher-finish" type="date" min={start} bind:value={finish} on:change={changePeriod} /></div>
  </PlannerFilterBar>
  <PlannerToolbar slot="toolbar" ariaLabel="Обозначения расписания">
    <div slot="legend" class="planner-toolbar-legend legend"><span><i class="legend-dot selected"></i>Занятие</span><span>Пустая ячейка — занятий нет</span></div>
  </PlannerToolbar>
  {#if start && finish && start > finish}<p class="teacher-message error" role="alert">Дата окончания раньше даты начала.</p>{/if}
  {#if error}<div class="teacher-empty" role="alert"><h2>Не удалось загрузить расписание</h2><p>{error}</p><button type="button" on:click={load}>Попробовать ещё раз</button></div>
  {:else if loading}<div class="teacher-empty" role="status"><h2>Загружаем расписание</h2><p>Получаем занятия преподавателя из расписания ОмГТУ.</p></div>
  {:else if !loaded}<div class="teacher-empty"><span class="empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="7.5" r="3.5"/><path d="M5 20v-1.5a7 7 0 0 1 14 0V20"/></svg></span><h2>Выберите преподавателя</h2><p>Начните вводить фамилию и укажите период. Расписание загрузится автоматически.</p></div>
  {:else}
    {#each weeks as week, index (week.monday)}
      <div class="week-block">
        <div class="week-title"><div><span>НЕДЕЛЯ {String(index + 1).padStart(2, '0')}</span><h3>{dateShort(week.monday)} — {dateShort(week.saturday)}</h3></div><span>ПН — СБ</span></div>
        <div class="table-scroll"><div class="schedule-table viewer-schedule-table" role="table" aria-label={`Расписание преподавателя за неделю ${dateShort(week.monday)}`}>
          <div class="table-row table-head" role="row"><div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>{#each week.dates as day, i}<div role="columnheader" class:today-column={day === currentDate}><div class="head-day-info"><strong>{dayNames[i]}</strong><span>{dateShort(day)}</span></div></div>{/each}</div>
          {#each week.rows as row (row.slot.number)}<div class="table-row" role="row"><div class="slot-label" role="rowheader"><strong>{String(row.slot.number).padStart(2, '0')}</strong><span>{row.slot.start}<br />{row.slot.end}</span></div>
            {#each row.cells as cell (cell.key)}<div role="cell" class="cell-wrap viewer-cell-wrap" class:today-column={cell.date === currentDate} class:viewer-cell-no-lessons={!cell.lanes.some((lane) => lane.lessons.length)} class:out-of-range={cell.outOfRange}>
              {#if cell.outOfRange}<span class="cell-muted">Вне периода</span>{:else}{#each cell.lanes as lane}{#each lane.lessons as lesson}<article class="teacher-lesson" class:teacher-planned-lesson={Boolean(lesson.planKind)}><strong>{lesson.discipline || 'Занятие'}</strong>{#if lesson.planKind}<span class="planned-lesson-label">{lesson.planKind === 'substitution' ? 'Замена' : lesson.planKind === 'consultation' ? 'Консультация' : lesson.planKind === 'retake' ? 'Пересдача' : 'Встреча'} · {lesson.planStatus === 'confirmed' ? 'подтверждено' : 'выбрано'}</span>{/if}{#if lesson.kindOfWork}<span>{lesson.kindOfWork}</span>{/if}{#if lesson.group || lesson.subgroup}<small>{[lesson.group, lesson.subgroup].filter(Boolean).join(' · ')}</small>{/if}{#if lesson.auditorium}<small>ауд. {lesson.auditorium}</small>{/if}</article>{/each}{/each}{/if}
            </div>{/each}</div>{/each}
        </div></div>
      </div>
    {/each}
  {/if}
</PlannerPageFrame>

<style>
  .teacher-picker{min-width:0}.teacher-picker-label{display:block;font-size:12px;color:#789083;font-weight:700;margin-bottom:8px}.teacher-picked{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:50px;padding:8px 12px;background:#f6f9f5;border:1px solid #dce8dc;border-radius:8px}.teacher-picked strong,.teacher-picked small{display:block}.teacher-picked strong{font-size:13px;color:#234b3c}.teacher-picked small{font-size:11px;color:#81978a;margin-top:3px}.teacher-picked button,.teacher-empty button{border:0;background:none;color:#31755c;font-size:12px;font-weight:800;white-space:nowrap}.teacher-empty{text-align:center;padding:72px 20px;color:#769083}.teacher-empty h2{font-size:18px;color:#2a4b3b;margin:14px 0 8px}.teacher-empty p{font-size:13px;line-height:1.6;margin:0 auto;max-width:420px}.empty-icon{display:grid;place-items:center;width:50px;height:50px;background:#eaf4eb;border-radius:12px;margin:auto;color:#6b9d7c}.empty-icon svg{width:27px;height:27px}.teacher-message{padding:14px;color:#9c4c40}.teacher-lesson{display:grid;gap:4px;margin:5px;padding:9px;border:1px solid #dce8dc;border-radius:6px;background:#fff;color:#284c3b;font-size:12px;line-height:1.35;overflow-wrap:anywhere}.teacher-lesson span,.teacher-lesson small{color:#7a9184;font-size:11px}.teacher-lesson strong{font-size:12px}
  .teacher-planned-lesson{border-color:#9cc9b6;background:#f1f8f3}.planned-lesson-label{font-size:10px!important;font-weight:800;color:#31755c!important;text-transform:uppercase;letter-spacing:.04em}
</style>
