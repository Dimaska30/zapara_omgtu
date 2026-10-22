<script lang="ts">
  import { onMount } from 'svelte';
  import CustomSelect from './CustomSelect.svelte';
  import SearchField from './SearchField.svelte';
  import { COMMISSION_GROUPS } from './lib/commission';
  import {
    SLOTS,
    addDays,
    buildViewerWeeks,
    formatDate,
    formatShortName,
    getSchedule,
    hasWindowBefore,
    search,
    toIso,
    type ApiItem,
    type SearchItem,
    type Slot,
    type ViewerLessonDetail,
    type ViewerWeek
  } from './lib/schedule';

  const PFI_NAME = 'Прикладная математика и фундаментальная информатика';
  type Status = 'busy' | 'free' | 'window' | 'no-lessons' | 'error';
  type TeacherSlot = { teacher: SearchItem; status: Status; lessons: ViewerLessonDetail[] };
  type BoardRow = { date: string; slot: Slot; teachers: TeacherSlot[] };
  type SelectedLesson = { teacher: SearchItem; date: string; slot: Slot; lesson: ViewerLessonDetail };
  type Candidate = { person: SearchItem; status: Status | 'loading' | 'error' };

  function mondayOf(date: Date) {
    const monday = new Date(date);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    return monday;
  }
  const today = new Date();
  const firstMonday = mondayOf(today);
  let start = toIso(firstMonday);
  let finish = toIso(addDays(firstMonday, 12));
  let department = 'ПМФИ';
  let teachers: SearchItem[] = [];
  let weeks: ViewerWeek[] = [];
  let rows: BoardRow[] = [];
  let eventsByTeacher = new Map<string, ApiItem[]>();
  let failedTeacherIds = new Set<string>();
  let loading = false;
  let error = '';
  let hasLoaded = false;
  let selectedLesson: SelectedLesson | null = null;
  let pickedReplacement: SearchItem | null = null;
  let candidateMode: 'department' | 'topic' | 'other' = 'department';
  let topicId = '';
  let selectedOthers: SearchItem[] = [];
  let otherSchedules = new Map<string, ApiItem[]>();
  let otherLoading = false;
  let topicSchedules = new Map<string, ApiItem[]>();
  let topicFailedIds = new Set<string>();
  let otherFailedIds = new Set<string>();
  let topicLoading = false;
  let notice = '';

  function normalizedDepartment() {
    return department.trim().toLocaleLowerCase('ru-RU') === 'пмфи' ? PFI_NAME : department.trim();
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
              const status: Status = failedIds.has(person.id)
                ? 'error'
                : lessons.length
                ? 'busy'
                : dailySlots.length === 0
                  ? 'no-lessons'
                  : hasWindowBefore(dailySlots, slot.number) ? 'window' : 'free';
              return { teacher: person, status, lessons };
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
    loading = true;
    error = '';
    notice = '';
    selectedLesson = null;
    try {
      const query = normalizedDepartment();
      const found = await search(query, 'person');
      const lowerQuery = query.toLocaleLowerCase('ru-RU');
      const matching = found.filter((person) => person.description.toLocaleLowerCase('ru-RU').includes(lowerQuery));
      if (!matching.length) {
        teachers = [];
        rows = [];
        weeks = [];
        eventsByTeacher = new Map();
        failedTeacherIds = new Set();
        hasLoaded = true;
        if (found.length) error = `По запросу «${department}» преподаватели не найдены. Уточните название кафедры.`;
        return;
      }
      teachers = matching;
      const loaded = await fetchSchedules(matching, start, finish);
      eventsByTeacher = loaded.events;
      failedTeacherIds = loaded.failed;
      const entities = matching.map((person) => ({ id: person.id, label: person.label, type: 'person' as const }));
      weeks = buildViewerWeeks(start, finish, entities, eventsByTeacher);
      rows = makeRows(weeks, matching, failedTeacherIds);
      hasLoaded = true;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Не удалось загрузить расписания преподавателей.';
    } finally {
      loading = false;
    }
  }

  function lessonTitle(lesson: ViewerLessonDetail) {
    return [lesson.discipline, lesson.kindOfWork, lesson.group, lesson.auditorium ? `ауд. ${lesson.auditorium}` : ''].filter(Boolean).join(' · ');
  }

  function openReplacement(teacher: SearchItem, date: string, slot: Slot, lesson: ViewerLessonDetail) {
    selectedLesson = { teacher, date, slot, lesson };
    pickedReplacement = null;
    candidateMode = 'department';
    topicId = '';
    selectedOthers = [];
    topicSchedules = new Map();
    otherSchedules = new Map();
    notice = '';
  }

  function statusFor(events: Map<string, ApiItem[]>, person: SearchItem, date: string, slotNumber: number): Status {
    if (!events.has(person.id)) return 'error';
    const personWeeks = buildViewerWeeks(start, finish, [{ id: person.id, label: person.label, type: 'person' }], events);
    const busySlots: number[] = [];
    let busy = false;
    for (const week of personWeeks) {
      for (const row of week.rows) {
        const cell = row.cells.find((item) => item.date === date);
        const lane = cell?.lanes[0];
        if (lane?.lessons.length) busySlots.push(row.slot.number);
        if (row.slot.number === slotNumber && lane?.lessons.length) busy = true;
      }
    }
    if (busy) return 'busy';
    if (!busySlots.length) return 'no-lessons';
    return hasWindowBefore(busySlots, slotNumber) ? 'window' : 'free';
  }

  $: selectedTopic = COMMISSION_GROUPS.find((group) => group.id === topicId);
  $: topicPeople = selectedTopic?.people.filter((person) => person.id !== selectedLesson?.teacher.id) ?? [];
  function getDepartmentCandidates(selection: SelectedLesson | null): Candidate[] {
    if (!selection) return [];
    const row = rows.find((item) => item.date === selection.date && item.slot.number === selection.slot.number);
    return row?.teachers.filter((item) => item.teacher.id !== selection.teacher.id).map((item) => ({ person: item.teacher, status: item.status })) ?? [];
  }
  $: departmentCandidates = getDepartmentCandidates(selectedLesson);
  $: topicCandidates = selectedLesson ? topicPeople.map((person) => ({
    person,
    status: topicFailedIds.has(person.id) ? 'error' as const : topicSchedules.has(person.id) ? statusFor(topicSchedules, person, selectedLesson!.date, selectedLesson!.slot.number) : topicLoading ? 'loading' as const : 'error' as const
  })) : [];
  $: otherCandidates = selectedLesson ? selectedOthers.map((person) => ({
    person,
    status: otherFailedIds.has(person.id) ? 'error' as const : otherSchedules.has(person.id) ? statusFor(otherSchedules, person, selectedLesson!.date, selectedLesson!.slot.number) : otherLoading ? 'loading' as const : 'error' as const
  })) : [];

  async function chooseTopic(id: string) {
    topicId = id;
    topicSchedules = new Map();
    topicFailedIds = new Set();
    if (!id || !selectedLesson) return;
    const people = COMMISSION_GROUPS.find((group) => group.id === id)?.people.filter((person) => person.id !== selectedLesson?.teacher.id) ?? [];
    topicLoading = true;
    try { const loaded = await fetchSchedules(people, start, finish); topicSchedules = loaded.events; topicFailedIds = loaded.failed; }
    finally { topicLoading = false; }
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

  function candidateStatusText(status: Candidate['status']) {
    return status === 'error' ? 'нет данных' : status === 'busy' ? 'занят' : status === 'free' ? 'свободен' : status === 'window' ? 'свободен · окно' : status === 'no-lessons' ? 'нет пар сегодня' : status === 'loading' ? 'загружаем…' : 'ошибка расписания';
  }

  function confirmReplacement(candidate: Candidate) {
    if (candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons') return;
    pickedReplacement = candidate.person;
    notice = `${candidate.person.label} выбран(а) как замена на ${formatDate(selectedLesson!.date)}, ${selectedLesson!.slot.start}–${selectedLesson!.slot.end}.`;
  }

  onMount(() => { void refreshBoard(); });
</script>

<div class="workspace substitution-workspace">
  <div class="breadcrumb"><span>Главная</span><span>/</span><span>Замены</span></div>
  <section class="workspace-heading"><div><span class="section-kicker">ПЛАНИРОВАНИЕ / 03</span><h1>Замены занятий<span class="heading-period">.</span></h1><p>Найдите занятие на кафедре и подберите свободного коллегу для замены.</p></div><div class="heading-decoration" aria-hidden="true">⇄</div></section>

  <section class="substitution-controls" aria-label="Фильтры расписания замен">
    <div class="sub-filter department-filter"><label for="sub-department">Кафедра</label><div class="sub-input-with-note"><input id="sub-department" bind:value={department} on:keydown={(event) => event.key === 'Enter' && refreshBoard()} placeholder="Например, ПМФИ" /><span>Введите ПМФИ или название другой кафедры</span></div></div>
    <div class="sub-filter"><label for="sub-start">Период с</label><input id="sub-start" type="date" bind:value={start} /></div>
    <div class="sub-filter"><label for="sub-finish">по</label><input id="sub-finish" type="date" min={start} bind:value={finish} /></div>
    <button class="primary-button sub-load-button" type="button" disabled={loading || start > finish} on:click={refreshBoard}>{loading ? 'Загружаем…' : 'Показать расписание'}<span aria-hidden="true">↗</span></button>
  </section>

  <div class="substitution-legend" aria-label="Обозначения расписания">
    <span><i class="sub-legend-dot free"></i>Свободен, без окон</span>
    <span><i class="sub-legend-dot window"></i>Свободен, окно</span>
    <span><i class="sub-legend-dot no-lessons"></i>Нет пар сегодня</span>
    <span><i class="sub-legend-dot busy"></i>Занятие · нажмите для замены</span>
  </div>

  {#if error}<div class="sub-state error">{error}</div>
  {:else if loading && !hasLoaded}<div class="sub-state">Загружаю преподавателей кафедры и их расписания…</div>
  {:else if hasLoaded && !teachers.length}<div class="sub-state">По этому фильтру преподавателей не найдено.</div>
  {:else if hasLoaded}
    {#each weeks as week (week.monday)}
      <section class="week-block sub-week">
        <div class="week-title"><div><span>НЕДЕЛЯ</span><h3>{formatDate(week.monday)} — {formatDate(week.saturday)}</h3></div><span>ПН — СБ · {teachers.length} ПРЕПОДАВАТЕЛЕЙ</span></div>
        <div class="table-scroll">
          <table class="substitution-table">
            <thead><tr><th class="sub-date-heading">День / пара</th>{#each teachers as person (person.id)}<th title={`${person.label} · ${person.description}`}>{formatShortName(person.label)}<small>{person.label}</small></th>{/each}</tr></thead>
            <tbody>
              {#each rows.filter((row) => row.date >= week.monday && row.date <= week.saturday) as row (row.date + row.slot.number)}
                <tr class:sub-day-start={row.slot.number === 1}>
                  <th class="sub-slot-heading"><strong>{formatDate(row.date, { weekday: 'short', day: '2-digit', month: '2-digit' })}</strong><span>{row.slot.number} пара · {row.slot.start}–{row.slot.end}</span></th>
                  {#each row.teachers as teacherSlot (teacherSlot.teacher.id)}
                    <td>
                      {#if teacherSlot.status === 'busy'}
                        {#each teacherSlot.lessons as lesson (lesson.discipline + (lesson.group ?? '') + (lesson.auditorium ?? ''))}
                          <button type="button" class="sub-lesson" title={`${teacherSlot.teacher.label}: ${lessonTitle(lesson)}. Подобрать замену`} on:click={() => openReplacement(teacherSlot.teacher, row.date, row.slot, lesson)}>
                            <strong>{lesson.discipline}</strong><span>{lesson.kindOfWork ? `${lesson.kindOfWork} · ` : ''}{lesson.group ?? 'Занятие'}</span>
                          </button>
                        {/each}
                      {:else}
                        <span class="sub-status" class:status-free={teacherSlot.status === 'free'} class:status-window={teacherSlot.status === 'window'} class:status-no-lessons={teacherSlot.status === 'no-lessons'} class:status-error={teacherSlot.status === 'error'}>{teacherSlot.status === 'free' ? 'Свободен' : teacherSlot.status === 'window' ? 'Окно' : teacherSlot.status === 'error' ? 'Нет данных' : 'Нет пар'}</span>
                      {/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/each}
  {/if}
</div>

{#if selectedLesson}
  <div class="sub-modal-backdrop" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) selectedLesson = null; }} on:keydown={(event) => event.key === 'Escape' && (selectedLesson = null)}>
    <div class="sub-modal" role="dialog" aria-modal="true" aria-labelledby="replacement-title">
      <button class="sub-modal-close" type="button" aria-label="Закрыть" on:click={() => selectedLesson = null}>×</button>
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
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status === 'busy' || candidate.status === 'error' || candidate.status === 'loading'} on:click={() => confirmReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong><small>{candidate.person.description}</small></span><b>{candidateStatusText(candidate.status)}</b>
            </button>
          {:else}<p class="field-hint">Кроме заменяемого преподавателя на кафедре больше никого нет.</p>{/each}
        </div>
      {:else if candidateMode === 'topic'}
        <div class="sub-topic-select"><CustomSelect ariaLabel="Тематическая группа преподавателей" value={topicId} placeholder="Выберите тематическую группу" options={[{ value: '', label: 'Выберите тематическую группу' }, ...COMMISSION_GROUPS.map((group) => ({ value: group.id, label: group.label, extra: String(group.people.length) }))]} on:change={(event) => chooseTopic(event.detail)} /></div>
        {#if topicLoading}<p class="sub-loading-note">Проверяю расписание участников группы…</p>{/if}
        <div class="sub-candidate-list">
          {#each topicCandidates as candidate (candidate.person.id)}
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons'} on:click={() => confirmReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong></span><b>{candidateStatusText(candidate.status)}</b>
            </button>
          {:else}{#if topicId && !topicLoading}<p class="field-hint">В этой группе нет других участников.</p>{/if}{/each}
        </div>
      {:else}
        <SearchField type="person" placeholder="Найти преподавателя по ФИО" onPick={addOther} />
        {#if otherLoading}<p class="sub-loading-note">Проверяю расписание…</p>{/if}
        <div class="sub-candidate-list">
          {#each otherCandidates as candidate (candidate.person.id)}
            <button type="button" class="sub-candidate" class:is-picked={pickedReplacement?.id === candidate.person.id} class:status-free={candidate.status === 'free'} class:status-window={candidate.status === 'window'} class:status-no-lessons={candidate.status === 'no-lessons'} class:status-error={candidate.status === 'error'} disabled={candidate.status !== 'free' && candidate.status !== 'window' && candidate.status !== 'no-lessons'} on:click={() => confirmReplacement(candidate)}>
              <span><strong>{candidate.person.label}</strong><small>{candidate.person.description}</small></span><b>{candidateStatusText(candidate.status)}</b><i role="button" tabindex="0" aria-label={`Убрать ${candidate.person.label}`} on:click|stopPropagation={() => removeOther(candidate.person.id)} on:keydown={(event) => event.key === 'Enter' && removeOther(candidate.person.id)}>×</i>
            </button>
          {/each}
        </div>
      {/if}
      {#if notice}<p class="sub-notice" role="status">{notice}</p>{/if}
      <p class="sub-modal-footnote">Зелёный — свободен без окон · жёлтый — свободен в окно · красный — сегодня нет пар. Выбор помогает согласовать замену и не меняет исходное расписание.</p>
    </div>
  </div>
{/if}

<style>
  .substitution-workspace{max-width:1600px}
  .substitution-controls{display:grid;grid-template-columns:minmax(250px,1.4fr) minmax(145px,.7fr) minmax(145px,.7fr) auto;align-items:end;gap:14px;background:#fff;border:1px solid #e4eae3;border-radius:12px;padding:18px 20px;margin:0 0 18px}
  .sub-filter{display:flex;flex-direction:column;gap:7px;min-width:0}.sub-filter label{font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#799085}.sub-filter input{height:42px;min-width:0;border:1px solid #dce5de;border-radius:7px;background:#fbfdfb;padding:0 11px;color:#25463a;font:inherit;font-size:12px}.sub-input-with-note{display:flex;flex-direction:column;gap:5px}.sub-input-with-note span{font-size:9px;color:#8b9b92}.sub-load-button{height:42px;padding:0 15px;white-space:nowrap;font-size:11px}
  .substitution-legend{display:flex;align-items:center;flex-wrap:wrap;gap:9px 20px;padding:0 2px;margin:0 0 15px;color:#66796f;font-size:10px;font-weight:700}.substitution-legend span{display:flex;align-items:center;gap:6px}.sub-legend-dot{display:inline-block;width:11px;height:11px;border-radius:3px}.sub-legend-dot.free{background:#eaf4ed;border:1px solid #c9e6d2}.sub-legend-dot.window{background:#fdfaf0;border:1px solid #f2e2b6}.sub-legend-dot.no-lessons{background:#fde8e8;border:1px solid #f6c0c0}.sub-legend-dot.busy{background:#edf1ee;border:1px solid #dbe2dd}
  .sub-state{background:white;border:1px solid #e4eae3;border-radius:10px;padding:28px;color:#6c7f74;font-size:13px}.sub-state.error{color:#9d3838;background:#fff8f8;border-color:#f1d6d6}.sub-week .table-scroll{max-height:72vh}.substitution-table{border-collapse:separate;border-spacing:0;min-width:max-content;width:100%;font-size:10px}.substitution-table th,.substitution-table td{border-right:1px solid #edf0ea;border-bottom:1px solid #edf0ea;padding:5px;vertical-align:middle}.substitution-table thead th{position:sticky;top:0;z-index:3;background:#f7faf6;color:#38604b;text-align:center;min-width:134px;max-width:190px;height:45px}.substitution-table thead th small{display:block;margin-top:2px;font-size:8px;color:#91a096;font-weight:600}.substitution-table thead .sub-date-heading{left:0;z-index:5;min-width:130px;text-align:left}.substitution-table tbody th{position:sticky;left:0;z-index:2;background:#fbfdfb;text-align:left;min-width:130px}.sub-slot-heading strong,.sub-slot-heading span{display:block}.sub-slot-heading strong{font-size:10px;color:#315d49;text-transform:capitalize}.sub-slot-heading span{margin-top:3px;font-size:8px;color:#8b9a91;font-weight:600}.substitution-table tbody td{min-width:134px;max-width:190px;height:40px;background:#fff}.substitution-table .sub-day-start th,.substitution-table .sub-day-start td{border-top:2px solid #dfe8e1}.sub-lesson{display:flex;flex-direction:column;gap:3px;width:100%;min-height:38px;text-align:left;border:1px solid #dce5de;border-radius:5px;background:#f4f7f4;padding:5px 7px;color:#40584a}.sub-lesson:hover{background:#eaf4ed;border-color:#9dc9a9}.sub-lesson strong{font-size:9px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub-lesson span{font-size:8px;color:#8a9990;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub-status{display:block;padding:5px 6px;border-radius:5px;text-align:center;font-size:8px;font-weight:800}.status-free{background:#eaf4ed!important;color:#235c3b!important;border:1px solid #c9e6d2!important}.status-window{background:#fdfaf0!important;color:#7a541c!important;border:1px solid #f2e2b6!important}.status-no-lessons{background:#fff0f0!important;color:#a32a2a!important;border:1px solid #f6c0c0!important}.status-error{background:#f2f4f2!important;color:#718279!important;border:1px solid #dbe2dd!important}
  .sub-modal-backdrop{position:fixed;inset:0;z-index:1100;background:rgba(18,39,31,.42);display:grid;place-items:center;padding:18px}.sub-modal{position:relative;width:min(610px,100%);max-height:min(86vh,800px);overflow:auto;background:#fff;border:1px solid #dce7df;border-radius:14px;padding:26px;box-shadow:0 24px 70px rgba(17,47,35,.24)}.sub-modal-close{position:absolute;right:16px;top:13px;border:0;background:transparent;color:#75877d;font-size:25px}.sub-modal h2{margin:7px 35px 5px 0;color:#214b3b;font-size:23px;letter-spacing:-.04em}.sub-modal-context{margin:0 0 18px;color:#75867c;font-size:11px;line-height:1.7}.sub-candidate-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:4px;border-radius:8px;background:#f1f5f1;margin:15px 0}.sub-candidate-tabs button{border:0;background:transparent;border-radius:6px;padding:8px 10px;color:#718279;font-size:10px;font-weight:800}.sub-candidate-tabs button.active{background:#fff;color:#275b47;box-shadow:0 1px 4px #173e291a}.sub-topic-select{margin:0 0 10px}.sub-candidate-list{display:flex;flex-direction:column;gap:6px;margin-top:10px;max-height:300px;overflow:auto}.sub-candidate{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;text-align:left;border:1px solid #e3eae4;border-radius:7px;padding:9px 10px;background:#fff;color:#365543}.sub-candidate.is-picked{border-color:#6fa88a!important;box-shadow:inset 3px 0 #4d9472}.sub-candidate>span{display:flex;flex-direction:column;gap:3px;min-width:0}.sub-candidate strong{font-size:11px}.sub-candidate small{font-size:8px;color:#819187}.sub-candidate b{font-size:8px;white-space:nowrap;border-radius:4px;padding:5px 7px}.sub-candidate.status-free b{background:#dcefe1}.sub-candidate.status-window b{background:#faeec7}.sub-candidate.status-no-lessons b{background:#fbdede}.sub-candidate:disabled{cursor:default;opacity:.85}.sub-candidate:not(:disabled):hover{filter:brightness(.97)}.sub-candidate i{font-style:normal;font-size:17px;color:#829187}.sub-loading-note{margin:10px 0 0;color:#79897f;font-size:10px}.sub-notice{background:#eef7f0;border:1px solid #cfe6d3;border-radius:7px;padding:10px;color:#28623c;font-size:11px}.sub-modal-footnote{margin:15px 0 0;color:#849289;font-size:9px;line-height:1.6}
  @media(max-width:900px){.substitution-controls{grid-template-columns:1fr 1fr}.department-filter{grid-column:span 2}.sub-load-button{width:100%;justify-content:center}}
  @media(max-width:560px){.substitution-controls{grid-template-columns:1fr}.department-filter{grid-column:auto}.sub-modal{padding:20px}.sub-candidate-tabs button{flex:1}.substitution-legend{gap:8px 12px}}
</style>
