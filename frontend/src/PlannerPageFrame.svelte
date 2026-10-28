<script lang="ts">

  export let section = '';
  export let sectionNumber = '';
  export let title = '';
  export let description = '';
  export let icon = '';
  export let breadcrumb = '';
</script>

<div class="workspace substitution-workspace">
  <h1 class="visually-hidden">{title}</h1>
  {#if $$slots.headingAction}<div class="workspace-heading-action"><slot name="headingAction" /></div>{/if}

  <slot name="filters" />
  <slot name="toolbar" />
  <slot />
</div>
