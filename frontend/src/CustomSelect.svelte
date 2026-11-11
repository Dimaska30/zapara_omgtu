<script lang="ts">
  import { createEventDispatcher, onMount, onDestroy, tick } from 'svelte';

  export let value: any = null;
  export let options: { value: any; label: string; extra?: string }[] = [];
  export let placeholder = 'Выберите...';
  export let id: string | undefined = undefined;
  export let ariaLabel: string | undefined = undefined;
  export let disabled = false;
  export let size: 'default' | 'sm' = 'default';
  export let loading = false;

  const dispatch = createEventDispatcher<{ change: any }>();

  let isOpen = false;
  let rootEl: HTMLElement;
  let dropUp = false;
  let dropMaxHeight = 240;

  $: selectedOption = options.find((o) => o.value === value);
  $: displayLabel = selectedOption ? selectedOption.label : placeholder;

  async function toggle() {
    if (disabled) return;
    isOpen = !isOpen;
    if (isOpen) {
      await tick();
      updateDropdownPlacement();
    }
  }

  function updateDropdownPlacement() {
    if (!rootEl) return;
    const bounds = rootEl.closest('.sub-modal')?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
    const trigger = rootEl.getBoundingClientRect();
    const above = Math.max(0, trigger.top - bounds.top - 12);
    const below = Math.max(0, bounds.bottom - trigger.bottom - 12);
    dropUp = below < 240 && above > below;
    dropMaxHeight = Math.max(96, Math.min(240, (dropUp ? above : below) - 8));
  }

  function selectOption(optVal: any) {
    if (disabled) return;
    value = optVal;
    isOpen = false;
    dispatch('change', value);
  }

  function handleClickOutside(event: MouseEvent) {
    if (isOpen && rootEl && !rootEl.contains(event.target as Node)) {
      isOpen = false;
    }
  }

  function handleKeyDown(event: KeyboardEvent) {
    if (disabled) return;
    if (event.key === 'Escape' && isOpen) {
      isOpen = false;
      event.stopPropagation();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!isOpen) {
        isOpen = true;
      } else {
        const idx = options.findIndex((o) => o.value === value);
        if (idx < options.length - 1) selectOption(options[idx + 1].value);
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!isOpen) {
        isOpen = true;
      } else {
        const idx = options.findIndex((o) => o.value === value);
        if (idx > 0) selectOption(options[idx - 1].value);
      }
    }
  }

  onMount(() => {
    window.addEventListener('click', handleClickOutside, true);
  });

  onDestroy(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('click', handleClickOutside, true);
    }
  });
</script>

<div
  class="custom-select-wrap"
  class:size-sm={size === 'sm'}
  class:is-open={isOpen}
  class:is-disabled={disabled}
  bind:this={rootEl}
  on:keydown={handleKeyDown}
>
  <button
    type="button"
    {id}
    class="custom-select-trigger"
    aria-label={ariaLabel || displayLabel}
    aria-haspopup="listbox"
    aria-expanded={isOpen}
    {disabled}
    on:click={toggle}
  >
    <span class="custom-select-label" class:is-placeholder={!selectedOption}>
      {displayLabel}
    </span>
    <span class="custom-select-chevron" class:open={isOpen} aria-hidden="true">
      <svg width="10" height="7" viewBox="0 0 12 8" fill="none">
        <path d="M1.5 2L6 6.5L10.5 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </span>
  </button>

  {#if isOpen}
    <div class="custom-select-dropdown" class:drop-up={dropUp} style={`--dropdown-max-height:${dropMaxHeight}px`} role="listbox" aria-label={ariaLabel || 'Варианты'}>
      <ul class="custom-select-options">
        {#if options.length === 0}
          <li class="custom-select-empty">
            {loading ? 'Загрузка вариантов…' : 'Нет доступных вариантов'}
          </li>
        {:else}
          {#each options as opt, index (opt.value !== null && opt.value !== undefined ? String(opt.value) : `opt-${index}`)}
            {@const isSelected = opt.value === value}
            <li
              class="custom-select-option"
              class:selected={isSelected}
              role="option"
              aria-selected={isSelected}
              on:click={() => selectOption(opt.value)}
              on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && selectOption(opt.value)}
              tabindex="0"
            >
              <span class="option-label">{opt.label}</span>
              {#if opt.extra}
                <span class="option-extra">{opt.extra}</span>
              {/if}
              {#if isSelected}
                <span class="option-check" aria-hidden="true">✓</span>
              {/if}
            </li>
          {/each}
        {/if}
      </ul>
    </div>
  {/if}
</div>

<style>
  .custom-select-wrap {
    position: relative;
    width: 100%;
    user-select: none;
  }
  .custom-select-trigger {
    width: 100%;
    height: 44px;
    background-color: #f9fbf8;
    border: 1px solid #e2e9e1;
    border-radius: 8px;
    padding: 0 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-family: inherit;
    font-size: 12px;
    font-weight: 600;
    color: #244637;
    text-align: left;
    cursor: pointer;
    box-shadow: 0 1px 2px rgba(22, 54, 38, 0.04);
    transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
  }
  .size-sm .custom-select-trigger {
    height: 38px;
    border-radius: 8px;
    font-size: 12px;
  }
  .custom-select-trigger:hover:not(:disabled) {
    background-color: #ffffff;
    border-color: #83bca4;
  }
  .custom-select-trigger:focus-visible,
  .is-open .custom-select-trigger {
    outline: none;
    border-color: #3b8765;
    background-color: #ffffff;
    box-shadow: 0 0 0 3px rgba(59, 135, 101, 0.16);
  }
  .is-disabled .custom-select-trigger {
    opacity: 0.6;
    cursor: not-allowed;
    background-color: #f2f5f3;
  }
  .custom-select-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .custom-select-label.is-placeholder {
    color: #8fa597;
    font-weight: 500;
  }
  .custom-select-chevron {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #4a7560;
    flex-shrink: 0;
    transition: transform .2s ease;
  }
  .custom-select-chevron.open {
    transform: rotate(180deg);
  }
  .custom-select-dropdown {
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 4px);
    background: #ffffff;
    border: 1px solid #cad9ce;
    border-radius: 8px;
    box-shadow: 0 10px 28px rgba(20, 50, 36, 0.14), 0 2px 6px rgba(0, 0, 0, 0.04);
    z-index: 1000;
    max-height: var(--dropdown-max-height, 240px);
    overflow-y: auto;
    padding: 4px;
    animation: fadeIn .12s ease-out;
  }
  .custom-select-dropdown.drop-up {
    top: auto;
    bottom: calc(100% + 4px);
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .custom-select-options {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .custom-select-option {
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    color: #244637;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    cursor: pointer;
    transition: background-color .1s ease, color .1s ease;
    outline: none;
  }
  .custom-select-option:hover,
  .custom-select-option:focus-visible {
    background-color: #edf5f0;
    color: #1a4f3b;
  }
  .custom-select-option.selected {
    background-color: #e2f0e7;
    color: #154532;
    font-weight: 700;
  }
  .option-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .option-extra {
    font-size: 10.5px;
    color: #698375;
    font-weight: 500;
  }
  .option-check {
    font-size: 12px;
    color: #2b7565;
    font-weight: 800;
    flex-shrink: 0;
  }
  .custom-select-empty {
    padding: 12px 10px;
    font-size: 11.5px;
    color: #728c7f;
    text-align: center;
  }
  /* Custom slim scrollbar */
  .custom-select-dropdown::-webkit-scrollbar {
    width: 6px;
  }
  .custom-select-dropdown::-webkit-scrollbar-track {
    background: #f4f7f5;
    border-radius: 4px;
  }
  .custom-select-dropdown::-webkit-scrollbar-thumb {
    background: #c5d7cb;
    border-radius: 4px;
  }
  .custom-select-dropdown::-webkit-scrollbar-thumb:hover {
    background: #9abfa7;
  }
</style>
