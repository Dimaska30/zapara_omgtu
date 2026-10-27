<script lang="ts">
  export let name: 'calendar' | 'teacher' | 'consultations' | 'retakes' | 'substitutions' | 'meetings' | 'arrow';
  export let size = 24;
</script>
<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {#if name === 'calendar'}
    <rect x="3.5" y="5.5" width="17" height="15" rx="2" /><path d="M7.5 3.5v4M16.5 3.5v4M3.5 10h17M7.5 13.5h2M12.5 13.5h2M7.5 17h2" />
  {:else if name === 'teacher'}
    <circle cx="12" cy="7.5" r="3.5" /><path d="M5 20v-1.5a7 7 0 0 1 14 0V20M4 20h16" />
  {:else if name === 'consultations'}
    <path d="M5 18.5 3 21l.7-4.4A8.5 8.5 0 1 1 8 20M8 10h8M8 13.5h5" />
  {:else if name === 'retakes'}
    <path d="M4 7.5A9 9 0 0 1 19 6l2 2M21 4v4h-4M20 16.5A9 9 0 0 1 5 18l-2-2M3 20v-4h4" />
  {:else if name === 'substitutions'}
    <path d="M3 8h17M16 4l4 4-4 4M21 16H4M8 12l-4 4 4 4" />
  {:else if name === 'meetings'}
    <circle cx="9" cy="8" r="3" /><path d="M3.5 19v-1a5.5 5.5 0 0 1 11 0v1M16 5.5a3 3 0 0 1 0 5.8M17 13.2a5.2 5.2 0 0 1 3.5 4.9V19" />
  {:else}
    <path d="M5 12h14M14 7l5 5-5 5" />
  {/if}
</svg>
