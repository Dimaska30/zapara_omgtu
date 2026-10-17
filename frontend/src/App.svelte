<script lang="ts">
  import SearchField from './SearchField.svelte';
  import { buildWeeks, formatDate, getSchedule, toIso, type ApiItem, type Cell, type Group, type SearchItem, type Week } from './lib/schedule';
  import { COMMISSION_GROUPS } from './lib/commission';

  type Page = 'home' | 'consultations' | 'retakes' | 'substitutions' | 'meetings';
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
  };
  const sections: { page: Page; number: string; name: string; description: string; icon: string; active: boolean }[] = [
    { page: 'retakes', number: '01', name: 'Пересдачи', description: 'Подберите время для повторной сдачи', icon: '↗', active: true },
    { page: 'consultations', number: '02', name: 'Консультации', description: 'Найдите общие свободные окна', icon: '◷', active: true },
    { page: 'substitutions', number: '03', name: 'Замены', description: 'Найдите коллег для замены занятий', icon: '⇄', active: true },
    { page: 'meetings', number: '04', name: 'Рабочие встречи', description: 'Найдите общее время для коллег', icon: '✧', active: true }
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
    requestController?.abort();
    requestNumber++;
    loading = false;
    weeks = [];
    selected = new Set();
    hasGenerated = false;
    error = '';
    failedCommissionCount = 0;
    loadedSchedule = null;
  }

  function rebuildFromLoaded() {
    if (!loadedSchedule) return;
    const data = loadedSchedule;
    const result = buildWeeks(
      data.start, data.finish, data.teacherEvents, data.groupEvents, data.groups,
      data.candidates.length ? { people: data.candidates, events: data.commissionEvents, failedIds: data.failedIds, mercy: data.mode === 'meeting' ? false : mercy } : undefined,
      data.mode
    );
    weeks = result.weeks;
    unknownDates = result.unknownDates;
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
      const [teacherSchedule, commissionSchedules, groupSchedules] = await Promise.all([
        isMeeting ? Promise.resolve([] as ApiItem[]) : getSchedule('person', teacher!.id, start, finish, controller.signal),
        loadCommissionSchedules(candidates, controller.signal),
        Promise.all((isMeeting || page === 'substitutions' ? [] : groups).map((group) => getSchedule('group', group.id, start, finish, controller.signal)))
      ]);
      if (current !== requestNumber) return;
      const activeGroups = isMeeting || page === 'substitutions' ? [] : groups;
      const groupEvents = new Map<string, ApiItem[]>(activeGroups.map((group, i) => [group.id, groupSchedules[i]]));
      loadedSchedule = { start, finish, teacherEvents: teacherSchedule, groupEvents, groups: activeGroups, candidates, commissionEvents: commissionSchedules.events, failedIds: commissionSchedules.failedIds, mode: isMeeting ? 'meeting' : page === 'substitutions' ? 'substitution' : 'availability' };
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
    if (next.has(cell.key)) next.delete(cell.key); else next.add(cell.key);
    selected = next;
  }

  function go(next: Page) { if (next !== page) invalidate(); if (next === 'retakes' && commissionTeachers.length > 2) commissionTeachers = commissionTeachers.slice(0, 2); page = next; window.scrollTo({ top: 0, behavior: 'smooth' }); }
  function dateShort(value: string) { return formatDate(value, { day: '2-digit', month: '2-digit' }); }
  function freeCommission(cell: Cell) { return cell.commission.filter((entry) => entry.available).map((entry) => entry.person.label); }
  function commissionReason(reason: 'free' | 'busy' | 'no-lessons' | 'load-error') { return reason === 'free' ? (page === 'substitutions' ? 'может заменить' : 'может присутствовать') : reason === 'busy' ? 'занят в это время' : reason === 'no-lessons' ? 'нет пар в этот день' : 'расписание не загрузилось'; }
</script>

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
                  <select class="group-select" aria-label="Тематическая группа преподавателей" value={commissionGroupId} on:change={(event) => changeCommissionGroup((event.currentTarget as HTMLSelectElement).value)}><option value="">Выберите группу</option>{#each COMMISSION_GROUPS as group}<option value={group.id}>{group.label} · {group.people.length}</option>{/each}</select>
                  {#if selectedCommissionGroup}<p class="field-hint">Кандидатов: {selectedCommissionGroup.people.filter((person) => person.id !== teacher?.id).length}. {page === 'substitutions' ? 'Заменяемый преподаватель' : 'Основной преподаватель'} в число кандидатов не входит.</p>{/if}
                {/if}
              </div>
              <div class="mercy-field"><label class="mercy-switch"><input type="checkbox" checked={mercy} on:change={(event) => changeMercy((event.currentTarget as HTMLInputElement).checked)} /><span class="mercy-track"></span><strong>Милосердие</strong></label><p>Не считать доступными преподавателей, у которых в этот день совсем нет пар.</p></div>
            {/if}

            {#if page !== 'substitutions' && page !== 'meetings'}<div class="field-block"><div class="field-head"><label>Учебные группы</label><span>{page === 'retakes' && retakeMode === 'commission' ? '03' : '02'}</span></div>
              <SearchField type="group" placeholder="Например, М-251" onPick={addGroup} />
              {#if groups.length}<div class="group-chips">{#each groups as group (group.id)}<span class="group-chip">{group.label}<button type="button" on:click={() => removeGroup(group.id)} aria-label={`Удалить группу ${group.label}`}>×</button></span>{/each}</div>{:else}<p class="field-hint">Можно добавить любое количество групп</p>{/if}
            </div>{/if}

            <div class="field-block date-block"><div class="field-head"><label>Период</label><span>{page === 'retakes' && retakeMode === 'commission' ? '04' : page === 'meetings' ? '02' : '03'}</span></div><div class="date-fields"><div><label for="start-date">С</label><input id="start-date" type="date" value={start} on:change={(event) => changeStart((event.currentTarget as HTMLInputElement).value)} /></div><div><label for="end-date">ПО</label><input id="end-date" type="date" min={start} value={finish} on:change={(event) => changeFinish((event.currentTarget as HTMLInputElement).value)} /></div></div></div>
            {#if start && finish && start > finish}<p class="form-error">Дата окончания раньше даты начала.</p>{/if}
            <button class="primary-button generate-button" type="button" disabled={(page === 'meetings' ? !meetingTeachers.length : !teacher) || (page !== 'meetings' && page !== 'substitutions' && !groups.length) || !start || !finish || start > finish || loading || ((page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && (commissionChoice === 'people' ? !commissionTeachers.length : !commissionGroupId))} on:click={generate}>{loading ? 'Загружаем расписание…' : page === 'substitutions' ? 'Показать замены' : 'Показать свободное время'}<span aria-hidden="true">↗</span></button>
            <div class="panel-note"><span>ⓘ</span><p>{page === 'substitutions' ? 'Выбирайте занятия заменяемого преподавателя. Доступность коллег показана под каждой парой и не ограничивает выбор.' : page === 'meetings' ? 'Зелёные слоты свободны у всех выбранных преподавателей.' : 'Расписание загружается с сайта ОмГТУ. В таблице можно выбрать подходящие пары.'}</p></div>
          </aside>

          <section class="results-panel" aria-live="polite">
            <div class="results-header"><div><span class="panel-number">02 — РЕЗУЛЬТАТ</span><h2>{page === 'substitutions' ? 'Занятия и доступные замены' : 'Общие свободные окна'}</h2></div>{#if hasGenerated}<span class="week-count">{weeks.length} {weeks.length === 1 ? 'неделя' : weeks.length < 5 ? 'недели' : 'недель'}</span>{/if}</div>
            {#if error}<div class="state-card error-card"><span class="state-icon">!</span><h3>Не удалось получить расписание</h3><p>{error}</p><button type="button" on:click={generate}>Повторить запрос ↗</button></div>
            {:else if loading}<div class="state-card"><span class="state-icon loading-icon">◷</span><h3>Сопоставляем расписания</h3><p>{page === 'substitutions' ? 'Загружаем занятия и расписания возможных замещающих преподавателей.' : page === 'meetings' ? 'Загружаем расписания выбранных преподавателей.' : 'Загружаем основного преподавателя, группы и выбранный состав комиссии.'}</p></div>
            {:else if !hasGenerated}<div class="state-card empty-card"><div class="empty-illustration"><span>01</span><span>02</span><span>03</span><span>04</span></div><h3>{page === 'substitutions' ? 'Здесь появятся занятия' : 'Здесь появятся свободные окна'}</h3><p>{page === 'substitutions' ? 'Выберите преподавателя, которого нужно заменить, укажите возможных заменяющих и период. Мы покажем его занятия и доступность коллег.' : page === 'meetings' ? 'Добавьте преподавателей и укажите даты. Мы покажем пары, свободные у всех выбранных.' : `Выберите преподавателя, добавьте группы и укажите даты.${page === 'retakes' && retakeMode === 'commission' ? ' Для комиссии укажите людей или тематическую группу.' : ''} Мы покажем общие свободные пары по неделям.`}</p></div>
            {:else}
              <div class="legend"><span><i class="legend-dot free"></i>Можно выбрать</span><span><i class="legend-dot selected"></i>Выбрано</span><span><i class="legend-dot unavailable"></i>{page === 'substitutions' ? 'Нет занятия' : 'Нет общего окна'}</span>{#if page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')}<span>{page === 'substitutions' ? 'Доступность заменяющих' : 'Комиссия'} указана справочно под слотом</span>{/if}</div>
              {#if unknownDates > 0}<p class="warning-note">У {unknownDates} занятий не удалось определить дату. Проверьте итог по исходному расписанию.</p>{/if}
              {#if failedCommissionCount > 0}<p class="warning-note">Не удалось загрузить расписание {failedCommissionCount} {failedCommissionCount === 1 ? 'преподавателя' : 'преподавателей'} {page === 'substitutions' ? 'для замены' : page === 'meetings' ? 'для встречи' : 'комиссии'}. {page === 'meetings' ? 'Общие свободные слоты нельзя определить, пока не загрузятся все расписания.' : 'Они не отмечены как доступные.'}</p>{/if}
              {#each weeks as week, index}
                <div class="week-block"><div class="week-title"><div><span>НЕДЕЛЯ {String(index + 1).padStart(2, '0')}</span><h3>{dateShort(week.monday)} — {dateShort(week.saturday)}</h3></div><span>ПН — СБ</span></div>
                  <div class="table-scroll"><div class="schedule-table" role="table" aria-label={`Неделя ${dateShort(week.monday)} — ${dateShort(week.saturday)}`}>
                    <div class="table-row table-head" role="row"><div role="columnheader" class="time-heading">ПАРА / ВРЕМЯ</div>{#each week.dates as date, day}<div role="columnheader"><strong>{dayNames[day]}</strong><span>{dateShort(date)}</span></div>{/each}</div>
                    {#each week.rows as row}<div class="table-row" role="row"><div class="slot-label" role="rowheader"><strong>{String(row.slot.number).padStart(2, '0')}</strong><span>{row.slot.start}<br />{row.slot.end}</span></div>
                      {#each row.cells as cell}<div role="cell" class="cell-wrap"><button type="button" class="slot-cell" class:is-free={cell.available} class:is-selected={selected.has(cell.key)} class:show-candidates={(page === 'substitutions' || (page === 'retakes' && retakeMode === 'commission')) && commissionChoice === 'group' && selected.has(cell.key)} disabled={!cell.available} aria-pressed={cell.available ? selected.has(cell.key) : undefined} aria-label={cell.available ? page === 'meetings' ? `${formatDate(cell.date)}, ${row.slot.start}–${row.slot.end}, все преподаватели свободны` : page === 'substitutions' ? `${formatDate(cell.date)}, ${row.slot.start}–${row.slot.end}, занятие: ${cell.lessons.join(', ')}` : `${formatDate(cell.date)}, ${row.slot.start}–${row.slot.end}, свободны: ${cell.freeGroups.map((group) => group.label).join(', ')}` : `${formatDate(cell.date)}, ${row.slot.start}–${row.slot.end}, ${cell.outOfRange ? 'вне периода' : page === 'meetings' ? 'не все преподаватели свободны' : page === 'substitutions' ? 'нет занятия' : cell.teacherBusy ? 'преподаватель занят' : 'все группы заняты'}`} on:click={() => toggle(cell)}>
                        {#if cell.outOfRange}<span class="cell-muted">Вне периода</span>{:else if page === 'meetings'}{#if cell.available}<span class="cell-group-list">Свободны все</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else}<span class="cell-muted">Занято</span>{/if}{:else if page === 'substitutions'}{#if cell.teacherBusy}<span class="cell-group-list lesson-summary">{cell.lessons.join('; ')}</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{:else}<span class="cell-muted">Нет занятия</span>{/if}{:else if cell.teacherBusy}<span class="cell-muted">Занято</span>{:else if !cell.freeGroups.length}<span class="cell-muted">Нет групп</span>{:else}<span class="cell-group-list">{cell.freeGroups.map((group) => group.label).join(', ')}</span><span class="cell-check">{selected.has(cell.key) ? '✓' : '+'}</span>{/if}
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
      {#if hasGenerated}<div class="selection-bar" aria-live="polite"><span class="selection-count">{selectedCount}</span><span><strong>Выбрано {page === 'substitutions' ? 'занятий' : 'слотов'}</strong><small>{selectedCount ? `В ${new Set(selectedDetails.map((item) => item.cell.date)).size} дн.` : page === 'substitutions' ? 'Нажмите на занятие' : 'Нажмите на свободную пару'}</small></span>{#if selectedCount}<button type="button" on:click={() => selected = new Set()}>Очистить</button>{/if}</div>{/if}
    {/if}
  </main>

  <footer class="footer"><span><strong>Запара</strong> / пространство преподавателя</span><span>Разработал ассистент кафедры ПМиФИ Плескунов Д.А.</span></footer>
</div>
