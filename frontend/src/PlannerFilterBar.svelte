<script lang="ts">
  export let ariaLabel = 'Фильтры расписания';
  export let className = '';
</script>

<section class="planner-filter-bar {className}" aria-label={ariaLabel}>
  <slot />
</section>
