<script lang="ts">
  import { onDestroy } from 'svelte';
  import { search, type SearchItem } from './lib/schedule';

  export let type: 'person' | 'group' | 'auditorium';
  export let placeholder: string;
  export let onPick: (item: SearchItem) => void;

  let query = '';
  let suggestions: SearchItem[] = [];
  let loading = false;
  let error = '';
  let expanded = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let requestNumber = 0;
  const resultsId = `search-results-${Math.random().toString(36).slice(2)}`;

  function update(value: string) {
    query = value;
    suggestions = [];
    error = '';
    expanded = type === 'auditorium' ? value.trim().length >= 1 : value.trim().length > 3;
    loading = false;
    clearTimeout(timer);
    controller?.abort();
    const current = ++requestNumber;
    if (!expanded) return;
    timer = setTimeout(async () => {
      controller = new AbortController();
      loading = true;
      try {
        const results = await search(value.trim(), type, controller.signal);
        if (current === requestNumber) suggestions = results;
      } catch (cause) {
        if (current === requestNumber && !(cause instanceof DOMException && cause.name === 'AbortError')) {
          error = cause instanceof Error ? cause.message : 'Не удалось выполнить поиск.';
        }
      } finally {
        if (current === requestNumber) loading = false;
      }
    }, 280);
  }

  function pick(item: SearchItem) {
    clearTimeout(timer);
    controller?.abort();
    requestNumber++;
    query = '';
    suggestions = [];
    expanded = false;
    onPick(item);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') expanded = false;
    if (event.key === 'Enter' && expanded && suggestions.length) {
      event.preventDefault();
      pick(suggestions[0]);
    }
  }

  onDestroy(() => { clearTimeout(timer); controller?.abort(); });
</script>

<div class="search-field">
  <div class="search-input-wrap">
    <svg class="search-icon" width="19" height="19" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4.2 4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    <input
      type="search"
      autocomplete="off"
      aria-label={type === 'person' ? 'Поиск преподавателя' : type === 'auditorium' ? 'Поиск аудитории' : 'Поиск группы'}
      aria-expanded={expanded}
      aria-controls={resultsId}
      {placeholder}
      value={query}
      on:input={(event) => update((event.currentTarget as HTMLInputElement).value)}
      on:keydown={onKeydown}
      on:focus={() => { if (type === 'auditorium' ? query.trim().length >= 1 : query.trim().length > 3) expanded = true; }}
      on:blur={() => setTimeout(() => expanded = false, 150)}
    />
    {#if loading}<span class="search-spinner" aria-label="Поиск"></span>{/if}
  </div>
  {#if expanded}
    <div class="suggestions" id={resultsId} role="listbox">
      {#if error}
        <p class="suggestion-message error">{error}</p>
      {:else if loading && !suggestions.length}
        <p class="suggestion-message">Ищем совпадения…</p>
      {:else if !suggestions.length}
        <p class="suggestion-message">Ничего не найдено</p>
      {:else}
        {#each suggestions as item (item.id)}
          <button type="button" class="suggestion" role="option" aria-selected="false" on:mousedown|preventDefault={() => pick(item)}>
            <span class="suggestion-label">{item.label}</span>
            {#if item.description && item.description !== item.label}<small>{item.description}</small>{/if}
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</div>
