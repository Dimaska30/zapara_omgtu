<script lang="ts">
  export let ariaLabel = 'Параметры отображения расписания';
</script>

<div class="planner-toolbar" aria-label={ariaLabel}>
  <slot name="legend" />
  <slot name="options" />
</div>
