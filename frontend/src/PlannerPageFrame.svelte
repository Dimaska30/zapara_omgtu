<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let section = '';
  export let sectionNumber = '';
  export let title = '';
  export let description = '';
  export let icon = '';
  export let breadcrumb = '';
  const dispatch = createEventDispatcher<{ home: void }>();
</script>

<div class="workspace substitution-workspace">
  <div class="breadcrumb">
    <button type="button" on:click={() => dispatch('home')}>Главная</button>
    <span>/</span>
    <span>{breadcrumb}</span>
  </div>
  <section class="workspace-heading">
    <div>
      <span class="section-kicker">{section} / {sectionNumber}</span>
      <h1>{title}<span class="heading-period">.</span></h1>
      <p>{description}</p>
    </div>
    <div class="heading-decoration" aria-hidden="true">{icon}</div>
  </section>

  <slot name="filters" />
  <slot name="toolbar" />
  <slot />
</div>
