<script lang="ts">
  import { onMount } from 'svelte';
  import AppIcon from './AppIcon.svelte';
  import PlannerFilterBar from './PlannerFilterBar.svelte';
  import PlannerPageFrame from './PlannerPageFrame.svelte';
  import PlannerToolbar from './PlannerToolbar.svelte';
  import { AUDITORIUM_TYPE_CATEGORIES, SLOTS, addDays, formatDate, getPlannedEvents, mergePlannedEvents, toIso, type ApiItem, type AuditoriumItem, type Building } from './lib/schedule';

  const today = new Date();
  const monday = addDays(today, -((today.getDay() + 6) % 7));
  const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  let buildings: Building[] = [];
  let buildingOid = '';
  let start = toIso(monday);
  let finish = toIso(addDays(monday, 5));
  let auditoriums: AuditoriumItem[] = [];
  let events: ApiItem[] = [];
  let loaded = false;
  let loading = false;
  let loadingBuildings = true;
  let buildingCacheState = 'loading';
  let auditoriumCacheState = 'loading';
  let scheduleCacheState = 'loading';
  let error = '';
  let onlySlotsWithFree = false;
  let query = '';
  let auditoriumType = '';
  let minCapacity = '';
  let requestId = 0;
  let currentDate = toIso(new Date());
  let mounted = true;
  let loadTimer: number | null = null;
  let activeRoomTooltip: { room: AuditoriumItem; date: string; slot: (typeof SLOTS)[number]; targetRect: DOMRect } | null = null;

  type CacheReply<T> = { state: 'loading' | 'fresh' | 'stale' | 'unknown'; items?: T[]; coverage?: { state: string }[]; events?: ApiItem[]; complete?: boolean };

  async function cachedGet<T>(path: string): Promise<CacheReply<T>> {
    let response: Response;
    try { response = await fetch(`/backend-api/public${path}`); }
    catch { throw new Error('Не удалось связаться с серверным кешем расписания.'); }
    if (!response.ok) throw new Error(`Серверный кеш вернул ошибку ${response.status}.`);
    return response.json();
  }

  function pause(milliseconds: number) { return new Promise((resolve) => window.setTimeout(resolve, milliseconds)); }

  async function loadBuildings() {
    try {
      for (let attempt = 0; attempt < 150 && mounted; attempt++) {
        const reply = await cachedGet<ApiItem>('/dictionaries/buildings');
        const items = reply.items ?? [];
        if (items.length) {
          buildings = items.map((item) => ({ buildingOid: Number(item.buildingOid), name: String(item.name ?? item.abbr ?? 'Корпус'), abbr: String(item.abbr ?? item.name ?? '') })).filter((item) => Number.isFinite(item.buildingOid) && item.name !== 'Виртуальное').sort((a, b) => a.name.localeCompare(b.name, 'ru', { numeric: true }));
          buildingCacheState = reply.state;
          const preferred = buildings.find((item) => item.buildingOid === 18 || item.name.toLocaleUpperCase('ru-RU').includes('УЛК-8'));
          buildingOid = String((preferred ?? buildings[0])?.buildingOid ?? '');
          return;
        }
        await pause(2000);
      }
      if (mounted) error = 'Кеш корпусов пока пуст. Проверьте, что backend и worker запущены.';
    } catch (cause) {
      if (mounted) error = cause instanceof Error ? cause.message : 'Не удалось загрузить корпуса из серверного кеша.';
    } finally {
      if (mounted) {
        loadingBuildings = false;
        if (buildingOid) queueLoad(0);
      }
    }
  }

  async function loadAuditoriumDictionary(id: number, activeRequest: number) {
    for (let attempt = 0; attempt < 150 && activeRequest === requestId; attempt++) {
      const reply = await cachedGet<ApiItem>(`/dictionaries/auditoriums?buildingOid=${encodeURIComponent(id)}`);
      const items = reply.items ?? [];
      if (items.length) {
        auditoriumCacheState = reply.state;
        return items.map((item) => ({ auditoriumOid: Number(item.auditoriumOid), name: String(item.name ?? item.number ?? ''), number: String(item.number ?? item.name ?? ''), building: String(item.building ?? ''), buildingOid: Number(item.buildingOid), typeOfAuditorium: String(item.typeOfAuditorium ?? ''), amount: Number(item.amount ?? 0), computerEquipment: Number(item.computerEquipment ?? 0), mediaEquipment: Number(item.mediaEquipment ?? 0) })).filter((item) => Number.isFinite(item.auditoriumOid) && item.name.trim());
      }
      await pause(2000);
    }
    if (activeRequest !== requestId) throw new Error('Запрос заменён новым выбором периода.');
    throw new Error('Кеш аудиторий корпуса пока пуст. Worker продолжает загрузку; попробуйте ещё раз чуть позже.');
  }

  function schedulePath(id: number, from: string, to: string, includeEvents: boolean) {
    const params = new URLSearchParams({ start: from, finish: to, include_events: String(includeEvents) });
    return `/schedule/building/${encodeURIComponent(id)}?${params}`;
  }

  onMount(() => {
    mounted = true;
    const timer = window.setInterval(() => { currentDate = toIso(new Date()); }, 60_000);
    void loadBuildings();
    return () => {
      mounted = false;
      requestId++;
      window.clearInterval(timer);
      if (loadTimer !== null) window.clearTimeout(loadTimer);
    };
  });

  function changeFilters() {
    requestId++;
    loaded = false;
    loading = false;
    auditoriums = [];
    events = [];
    error = '';
    queueLoad();
  }

  function queueLoad(delay = 300) {
    if (loadTimer !== null) window.clearTimeout(loadTimer);
    if (!buildingOid || loadingBuildings) return;
    loadTimer = window.setTimeout(() => {
      loadTimer = null;
      void load();
    }, delay);
  }

  function showRoomTooltip(event: MouseEvent | FocusEvent, room: AuditoriumItem, date: string, slot: (typeof SLOTS)[number]) {
    const target = event.currentTarget as HTMLElement | null;
    if (target) activeRoomTooltip = { room, date, slot, targetRect: target.getBoundingClientRect() };
  }

  function positionRoomTooltip(node: HTMLElement, targetRect: DOMRect) {
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

  async function load() {
    const selectedBuilding = Number(buildingOid);
    if (!selectedBuilding || !start || !finish) return;
    if (start > finish) {
      loaded = false;
      loading = false;
      error = 'Дата окончания должна быть не раньше даты начала.';
      return;
    }
    if ((new Date(`${finish}T12:00:00`).getTime() - new Date(`${start}T12:00:00`).getTime()) / 86_400_000 > 13) {
      error = 'Выберите период не длиннее 14 дней.';
      return;
    }
    const id = ++requestId;
    loading = true;
    loaded = false;
    error = '';
    try {
      const [rooms, initialSchedule] = await Promise.all([
        loadAuditoriumDictionary(selectedBuilding, id),
        cachedGet<ApiItem>(schedulePath(selectedBuilding, start, finish, false))
      ]);
      if (id !== requestId) return;
      auditoriums = rooms.sort((a, b) => a.number.localeCompare(b.number, 'ru', { numeric: true }));
      let scheduleStatus = initialSchedule;
      if (scheduleStatus.complete) {
        const result = await cachedGet<ApiItem>(schedulePath(selectedBuilding, start, finish, true));
        events = result.events ?? [];
        scheduleCacheState = 'fresh';
      } else if (scheduleStatus.coverage?.some((item) => item.state === 'stale')) {
        const result = await cachedGet<ApiItem>(schedulePath(selectedBuilding, start, finish, true));
        events = result.events ?? [];
        scheduleCacheState = 'stale';
      } else {
        for (let attempt = 0; attempt < 180 && id === requestId; attempt++) {
          if (attempt) await pause(2000);
          scheduleStatus = await cachedGet<ApiItem>(schedulePath(selectedBuilding, start, finish, false));
          if (scheduleStatus.complete) break;
        }
        if (id !== requestId) return;
        if (!scheduleStatus.complete) throw new Error('Серверный кеш ещё загружает расписание. Worker обновляет данные постепенно; попробуйте позже.');
        const result = await cachedGet<ApiItem>(schedulePath(selectedBuilding, start, finish, true));
        events = result.events ?? [];
        scheduleCacheState = 'fresh';
      }
      if (id !== requestId) return;
      const planned = await getPlannedEvents(start, finish).catch(() => []);
      for (const room of auditoriums) {
        events = mergePlannedEvents(events, planned, 'auditorium', String(room.auditoriumOid)).map((event) =>
          event.target_kind === 'auditorium' ? { ...event, auditoriumOid: event.target_id } : event
        );
      }
      if (id !== requestId) return;
      loaded = true;
    } catch (cause) {
      if (id === requestId) error = cause instanceof Error ? cause.message : 'Не удалось загрузить занятость аудиторий.';
    } finally {
      if (id === requestId) loading = false;
    }
  }

  function isoDate(value: unknown): string | null {
    const text = String(value ?? '');
    const found = text.match(/(\d{4}[.-]\d{2}[.-]\d{2}|\d{2}[.-]\d{2}[.-]\d{4})/)?.[1];
    if (!found) return null;
    const parts = found.split(/[.-]/);
    return parts[0].length === 4 ? parts.join('-') : `${parts[2]}-${parts[1]}-${parts[0]}`;
  }

  function minutes(value: unknown): number | null {
    const match = String(value ?? '').match(/(\d{1,2}):(\d{2})/);
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  }

  function busyRoomIds(date: string, slot: (typeof SLOTS)[number]) {
    const slotStart = minutes(slot.start)!;
    const slotEnd = minutes(slot.end)!;
    const ids = new Set<string>();
    for (const event of events) {
      if (isoDate(event.date) !== date) continue;
      const rawId = event.auditoriumOid ?? event.auditoryOid ?? event.auditorium_id;
      if (rawId == null) continue;
      const eventStart = minutes(event.beginLesson ?? event.startTime ?? event.timeStart);
      const eventEnd = minutes(event.endLesson ?? event.endTime ?? event.timeEnd);
      if (eventStart == null || eventEnd == null || eventEnd <= eventStart || (eventStart < slotEnd && slotStart < eventEnd)) ids.add(String(rawId));
    }
    return ids;
  }

  function weekStarts() {
    const first = new Date(`${start}T12:00:00`);
    first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
    const starts: string[] = [];
    for (let cursor = first; toIso(cursor) <= finish; cursor = addDays(cursor, 7)) starts.push(toIso(cursor));
    return starts;
  }

  function dateAt(weekStart: string, day: number) { return toIso(addDays(new Date(`${weekStart}T12:00:00`), day)); }
  function dateLabel(date: string) { return formatDate(date, { day: '2-digit', month: '2-digit' }); }
  function freeRooms(date: string, slot: (typeof SLOTS)[number]) {
    const busy = busyRoomIds(date, slot);
    return filteredAuditoriums().filter((room) => !busy.has(String(room.auditoriumOid)));
  }

  function filteredAuditoriums() {
    const term = query.trim().toLocaleLowerCase('ru');
    const capacity = Number(minCapacity) || 0;
    return auditoriums.filter((room) => {
      const text = [room.name, room.number, room.building, room.typeOfAuditorium].join(' ').toLocaleLowerCase('ru');
      const matchesType = !auditoriumType || room.typeOfAuditorium.toLocaleLowerCase('ru').includes(auditoriumType);
      return (!term || text.includes(term)) && matchesType && room.amount >= capacity;
    });
  }
</script>

<PlannerPageFrame section="ПРОСМОТР" sectionNumber="03" breadcrumb="Аудитории" title="Свободные аудитории" description="Найдите свободные аудитории корпуса на выбранные даты." on:home>
  <PlannerFilterBar slot="filters" ariaLabel="Параметры просмотра свободных аудиторий" className="public-aud-controls">
    <div class="sub-filter"><label for="aud-building">Корпус</label><select id="aud-building" bind:value={buildingOid} on:change={changeFilters} disabled={loadingBuildings}><option value="">{loadingBuildings ? 'Загружаем корпуса…' : 'Выберите корпус'}</option>{#each buildings as building (building.buildingOid)}<option value={String(building.buildingOid)}>{building.name}</option>{/each}</select></div>
    <div class="sub-filter auditorium-search"><label for="aud-search">Поиск аудитории</label><input id="aud-search" type="search" bind:value={query} placeholder="Номер или название" /></div>
    <div class="sub-filter"><label for="aud-type">Тип аудитории</label><select id="aud-type" bind:value={auditoriumType}><option value="">Все типы</option>{#each AUDITORIUM_TYPE_CATEGORIES as category}<option value={category.matches[0]}>{category.label}</option>{/each}</select></div>
    <div class="sub-filter capacity-filter"><label for="aud-capacity">Мест от</label><input id="aud-capacity" type="number" min="0" bind:value={minCapacity} placeholder="Любая" /></div>
    <div class="sub-filter"><label for="aud-start">Период с</label><input id="aud-start" type="date" bind:value={start} on:change={changeFilters} /></div>
    <div class="sub-filter"><label for="aud-finish">по</label><input id="aud-finish" type="date" min={start} bind:value={finish} on:change={changeFilters} /></div>
  </PlannerFilterBar>
  <PlannerToolbar slot="toolbar" ariaLabel="Фильтр доступных аудиторий"><div slot="legend" class="planner-toolbar-legend public-aud-legend"><span><i class="legend-dot free"></i>Свободна в эту пару</span><span><i class="legend-dot selected"></i>Занята</span></div><div slot="options" class="planner-toolbar-options viewer-display-options"><label class:active={onlySlotsWithFree}><input type="checkbox" bind:checked={onlySlotsWithFree} />Скрывать пары без свободных аудиторий</label></div></PlannerToolbar>
  {#if error}<div class="state-card error-card" role="alert"><span class="state-icon"><AppIcon name="alert" size={28} /></span><h3>Не удалось показать аудитории</h3><p>{error}</p><button type="button" on:click={load}>Попробовать снова</button></div>
  {:else if loadingBuildings || loading}<div class="state-card" role="status"><span class="state-icon loading-icon"><AppIcon name="clock" size={28} /></span><h3>{loadingBuildings ? 'Загружаем корпуса' : 'Загружаем расписание аудиторий'}</h3><p>Получаем список помещений и пары выбранного корпуса.</p></div>
  {:else if !loaded}<div class="state-card empty-card"><span class="state-icon"><AppIcon name="building" size={28} /></span><h3>Выберите корпус и период</h3><p>Покажем по каждой паре, какие аудитории свободны.</p></div>
  {:else if !auditoriums.length}<div class="state-card empty-card"><h3>Аудитории не найдены</h3><p>В справочнике нет аудиторий для выбранного корпуса.</p></div>
  {:else}
    <p class="aud-data-note">Свободными считаются аудитории без занятий в расписании корпуса. Подходит фильтрам: {filteredAuditoriums().length} из {auditoriums.length}. {#if scheduleCacheState === 'stale' || auditoriumCacheState === 'stale' || buildingCacheState === 'stale'}Показан последний сохранённый снимок; кеш обновляется в фоне.{:else}Данные получены из кеша расписания.{/if}</p>
    {#each weekStarts() as weekStart, weekIndex (weekStart)}
      <section class="week-block public-aud-week">
        <header class="week-title"><div><span>НЕДЕЛЯ {String(weekIndex + 1).padStart(2, '0')}</span><h3>{dateLabel(weekStart)} — {dateLabel(dateAt(weekStart, 5))}</h3></div><span>ПН — СБ</span></header>
        <div class="public-aud-scroll"><table class="public-aud-table"><thead><tr><th>ПАРА / ВРЕМЯ</th>{#each dayNames as day, dayIndex}<th class:today-column={dateAt(weekStart, dayIndex) === currentDate}>{day}<small>{dateLabel(dateAt(weekStart, dayIndex))}</small></th>{/each}</tr></thead><tbody>
          {#each SLOTS as slot (slot.number)}<tr><th><strong>{String(slot.number).padStart(2, '0')}</strong><small>{slot.start}<br />{slot.end}</small></th>{#each dayNames as _, dayIndex (dayIndex)}{@const date = dateAt(weekStart, dayIndex)}<td class:today-column={date === currentDate} class:out-of-range={date < start || date > finish}>{#if date < start || date > finish}<span class="cell-muted">—</span>{:else}{@const free = freeRooms(date, slot)}{#if onlySlotsWithFree && free.length === 0}<span class="cell-muted">—</span>{:else}<span class="aud-free-count">{free.length} свободно</span>{#if free.length}<div class="aud-room-list">{#each free as room (room.auditoriumOid)}<span role="img" aria-label={`${room.name}, свободна ${dateLabel(date)}, ${slot.number} пара, ${slot.start}–${slot.end}`} title={`${room.name} · ${room.typeOfAuditorium || 'аудитория'}${room.amount ? ` · ${room.amount} мест` : ''}`} on:mouseenter={(event) => showRoomTooltip(event, room, date, slot)} on:mouseleave={() => activeRoomTooltip = null}>{room.number || room.name}</span>{/each}</div>{:else}<span class="cell-muted">{filteredAuditoriums().length ? 'Нет свободных аудиторий' : 'Нет аудиторий по фильтрам'}</span>{/if}{/if}{/if}</td>{/each}</tr>{/each}
        </tbody></table></div>
      </section>
    {/each}
  {/if}
</PlannerPageFrame>

{#if activeRoomTooltip}
  {@const item = activeRoomTooltip}
  <div class="custom-tooltip aud-room-tooltip" style="left:-9999px;top:-9999px" use:positionRoomTooltip={item.targetRect} role="tooltip">
    <div class="tooltip-header">
      <span class="tooltip-time">{formatDate(item.date, { weekday: 'short', day: 'numeric', month: 'short' })} · {item.slot.number} пара ({item.slot.start}–{item.slot.end})</span>
      <span class="tooltip-badge status-none">Свободна</span>
    </div>
    <div class="tooltip-body"><div class="tooltip-section"><div class="tooltip-entity-card card-free">
      <div class="entity-head"><strong class="entity-title">{item.room.name}</strong><span class="entity-badge">АУДИТОРИЯ</span></div>
      <div class="entity-desc"><div class="tooltip-meta-stack">
        <div class="tooltip-meta-line"><span class="party-label">Корпус:</span><strong>{item.room.building || buildings.find((building) => building.buildingOid === item.room.buildingOid)?.name || '—'}</strong></div>
        {#if item.room.typeOfAuditorium}<div class="tooltip-meta-line"><span class="party-label">Тип:</span><strong>{item.room.typeOfAuditorium}</strong></div>{/if}
        {#if item.room.amount}<div class="tooltip-meta-line"><span class="party-label">Мест:</span><strong>{item.room.amount}</strong></div>{/if}
        {#if item.room.computerEquipment}<div class="tooltip-meta-line"><span class="party-label">Компьютеры:</span><strong>{item.room.computerEquipment}</strong></div>{/if}
        {#if item.room.mediaEquipment}<div class="tooltip-meta-line"><span class="party-label">Медиаоборудование:</span><strong>{item.room.mediaEquipment}</strong></div>{/if}
      </div></div>
    </div></div></div>
  </div>
{/if}


