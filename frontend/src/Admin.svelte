<script lang="ts">
  import AppIcon from './AppIcon.svelte';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { account, accountChecking, setAccount, unreadNotifications, type DepartmentAccess } from './lib/account';

  export let activationToken = '';
  type Department = DepartmentAccess;
  type Teacher = { lecturerOid: number; person: string | number; fio: string; shortFIO?: string; chairOid: number };
  type Notice = { id: string; kind: string; payload: { event_date?: string; slot_number?: number }; read_at: string | null };
  type Account = { id: string; display_name: string; email: string; role: string; status: string; version: number; can_override_source_conflict: boolean; activated_at: string | null };
  let token = '';
  let email = '';
  let password = '';
  let newPassword = '';
  let departments: Department[] = [];
  let departmentId = '';
  let accounts: Account[] = [];
  let notices: Notice[] = [];
  let teachers: Teacher[] = [];
  let teacherId = '';
  let linkAccount: Account | null = null;
  let replacementTeacherId = '';
  let accountEmail = '';
  let accountName = '';
  let role = 'planner';
  let error = '';
  let message = '';
  let invitation = '';
  let working = false;
  let directoryState = '';
  let showInvite = false;
  let copied = false;
  let filter = '';
  let loading = false;
  $: activeDepartment = departments.find((item) => item.id === departmentId);
  $: visibleAccounts = accounts.filter((item) => `${item.display_name} ${item.email}`.toLocaleLowerCase('ru-RU').includes(filter.trim().toLocaleLowerCase('ru-RU')));
  $: unread = notices.filter((item) => !item.read_at).length;

  async function request(path: string, method = 'GET', body?: unknown) {
    const response = await fetch(`/backend-api${path}`, {
      method, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить действие');
    return data;
  }

  async function loadDepartments() {
    departments = await request('/admin/departments');
    const previous = get(account);
    departmentId = departments.some((item) => item.id === previous?.departmentId) ? previous!.departmentId : departments[0]?.id ?? '';
    const me = await request('/auth/me');
    setAccount({ token, user: me, departments, departmentId });
    await loadDepartment();
    notices = await request('/notifications');
    unreadNotifications.set(notices.filter((item) => !item.read_at).length);
  }
  async function loadDepartment() {
    if (!departmentId) return;
    const session = get(account);
    if (session) setAccount({ ...session, departments, departmentId });
    error = '';
    linkAccount = null;
    try {
      if (departments.find((item) => item.id === departmentId)?.role !== 'admin') { accounts = []; teachers = []; return; }
      accounts = await request(`/admin/departments/${departmentId}/users`);
      const directory = await request('/dictionaries/lecturers');
      directoryState = directory.state;
      const chair = departments.find((item) => item.id === departmentId)?.source_chair_oid;
      teachers = directory.items.filter((item: Teacher) => String(item.chairOid) === chair && item.person && item.lecturerOid);
      teacherId = '';
    } catch (e) { error = e instanceof Error ? e.message : 'Ошибка загрузки'; }
  }
  async function signIn() {
    error = ''; working = true;
    try { const result = await request('/auth/login', 'POST', { email, password }); token = result.access_token; password = ''; await loadDepartments(); }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка входа'; }
    finally { working = false; }
  }
  async function activate() {
    error = ''; working = true;
    try { await request('/auth/activate', 'POST', { token: activationToken, password: newPassword }); activationToken = ''; newPassword = ''; message = 'Пароль установлен. Войдите в аккаунт.'; }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка активации'; }
    finally { working = false; }
  }
  async function invite() {
    error = ''; message = ''; invitation = ''; copied = false; working = true;
    const teacher = teachers.find((item) => String(item.lecturerOid) === teacherId);
    if (!teacher) { error = 'Выберите преподавателя'; working = false; return; }
    try {
      const result = await request('/admin/users', 'POST', { email: accountEmail, display_name: accountName, department_id: departmentId, role, lecturer_oid: String(teacher.lecturerOid), person_id: String(teacher.person) });
      invitation = `${location.origin}${location.pathname}#activation=${encodeURIComponent(result.activation_token)}`;
      accountEmail = ''; accountName = ''; teacherId = ''; showInvite = false; message = 'Аккаунт создан. Передайте сотруднику одноразовую ссылку.'; await loadDepartment();
    } catch (e) { error = e instanceof Error ? e.message : 'Ошибка создания'; }
    finally { working = false; }
  }
  async function reset(account: Account) {
    error = ''; invitation = ''; copied = false;
    try { const result = await request(`/admin/departments/${departmentId}/users/${account.id}/password-reset`, 'POST'); invitation = `${location.origin}${location.pathname}#activation=${encodeURIComponent(result.reset_token)}`; message = 'Передайте сотруднику одноразовую ссылку для смены пароля.'; }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка восстановления'; }
  }
  async function toggle(account: Account) {
    error = '';
    try { await request(`/admin/departments/${departmentId}/users/${account.id}/membership`, 'PATCH', { version: account.version, status: account.status === 'active' ? 'suspended' : 'active' }); await loadDepartment(); }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка изменения доступа'; }
  }
  async function updateTeacherLink() {
    const teacher = teachers.find((item) => String(item.lecturerOid) === replacementTeacherId);
    if (!teacher || !linkAccount) { error = 'Выберите преподавателя'; return; }
    error = '';
    try {
      await request(`/admin/departments/${departmentId}/users/${linkAccount.id}/teacher-link`, 'PUT', { lecturer_oid: String(teacher.lecturerOid), person_id: String(teacher.person) });
      message = 'Преподаватель обновлён.'; linkAccount = null; replacementTeacherId = '';
    } catch (e) { error = e instanceof Error ? e.message : 'Ошибка изменения преподавателя'; }
  }
  async function toggleOverride(account: Account) {
    error = '';
    try { await request(`/admin/departments/${departmentId}/users/${account.id}/override-permission`, 'PUT', { enabled: !account.can_override_source_conflict }); await loadDepartment(); }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка изменения прав'; }
  }
  async function markRead(notice: Notice) {
    try { await request(`/notifications/${notice.id}/read`, 'POST'); notices = await request('/notifications'); unreadNotifications.set(notices.filter((item) => !item.read_at).length); }
    catch (e) { error = e instanceof Error ? e.message : 'Ошибка уведомления'; }
  }
  async function signOut() { try { await request('/auth/logout', 'POST'); } catch { /* Session is already gone. */ } token = ''; setAccount(null); accounts = []; departments = []; notices = []; invitation = ''; message = ''; }
  async function copyInvitation() {
    try { await navigator.clipboard.writeText(invitation); copied = true; }
    catch { error = 'Не удалось скопировать ссылку. Выделите её и скопируйте вручную.'; }
  }
  onMount(() => {
    if (activationToken) { message = 'Задайте пароль для своего аккаунта.'; return; }
    return account.subscribe((session) => {
      if (!session) { if (!working) { token = ''; accounts = []; departments = []; notices = []; } return; }
      if (session.token === token) return;
      token = session.token;
      loading = true;
      void (async () => { try { await loadDepartments(); } catch (e) { error = e instanceof Error ? e.message : 'Ошибка загрузки'; } finally { loading = false; } })();
    });
  });
</script>

<div class="account-page">
  {#if $accountChecking && !token && !activationToken}
    <div class="empty-state">Проверяем вход…</div>
  {:else if activationToken || !token}
    <div class="auth-layout">
      <div class="auth-intro"><span class="account-kicker">ЗАПАРА · КАФЕДРА</span><h1>{activationToken ? 'Добро пожаловать на кафедру.' : 'Планирование начинается здесь.'}</h1><p>{activationToken ? 'Установите пароль, чтобы получить доступ к рабочему пространству кафедры.' : 'Войдите, чтобы работать с консультациями, пересдачами, заменами и встречами.'}</p><div class="auth-note"><AppIcon name="calendar" size={24} /><div><strong>Расписание всегда под рукой</strong><small>Просматривать расписание можно без входа.</small></div></div></div>
      <section class="auth-panel"><div class="auth-panel-top"><span class="auth-symbol"><AppIcon name="teacher" size={22} /></span><span>АККАУНТ ПРЕПОДАВАТЕЛЯ</span></div><h2>{activationToken ? 'Установить пароль' : 'Вход в аккаунт'}</h2><p>{activationToken ? 'Придумайте пароль не короче 12 символов.' : 'Используйте данные, полученные от администратора.'}</p>
        {#if error}<p class="account-alert error" role="alert">{error}</p>{/if}{#if message}<p class="account-alert success" role="status">{message}</p>{/if}
        {#if activationToken}<form class="account-form" on:submit|preventDefault={activate}><label>Новый пароль<input type="password" bind:value={newPassword} minlength="12" autocomplete="new-password" placeholder="Не менее 12 символов" required /></label><button class="account-primary" disabled={working}>{working ? 'Сохраняем…' : 'Установить пароль'} <AppIcon name="arrow-up-right" size={17} /></button></form>
        {:else}<form class="account-form" on:submit|preventDefault={signIn}><label>Электронная почта<input type="email" bind:value={email} autocomplete="username" placeholder="name@example.ru" required /></label><label>Пароль<input type="password" bind:value={password} autocomplete="current-password" placeholder="Введите пароль" required /></label><button class="account-primary" disabled={working}>{working ? 'Входим…' : 'Войти'} <AppIcon name="arrow-up-right" size={17} /></button></form><p class="auth-help">Нет доступа или забыли пароль? Обратитесь к администратору кафедры.</p>{/if}
      </section>
    </div>
  {:else}
    <div class="account-breadcrumb"><span>Главная</span><span aria-hidden="true">/</span><strong>Аккаунт</strong></div>
    <header class="profile-header"><div><span class="account-kicker">ЛИЧНЫЙ КАБИНЕТ</span><h1>{$account?.user.display_name || 'Аккаунт'}</h1><p>{activeDepartment?.name || 'Кафедра'} <span class="profile-separator">·</span> {activeDepartment?.role === 'admin' ? 'Администратор' : activeDepartment?.role === 'planner' ? 'Сотрудник' : 'Просмотр'}</p></div><button class="account-outline" on:click={signOut}>Выйти <AppIcon name="arrow-up-right" size={17} /></button></header>
    {#if error}<p class="account-alert error" role="alert">{error}</p>{/if}{#if message}<p class="account-alert success" role="status">{message}</p>{/if}
    {#if invitation}<section class="invite-result" aria-label="Одноразовая ссылка"><div><strong>Ссылка готова</strong><p>Передайте её сотруднику. Она действует 24 часа и используется один раз.</p><input aria-label="Ссылка для сотрудника" readonly value={invitation} on:focus={(event) => event.currentTarget.select()} /></div><button class="account-outline" on:click={copyInvitation}>{copied ? 'Скопировано' : 'Копировать ссылку'}</button></section>{/if}
    {#if loading}<div class="empty-state">Загружаем данные аккаунта…</div>{:else}
      {#if activeDepartment?.role === 'viewer'}<p class="account-alert success">У вас доступ для просмотра расписания. Чтобы работать с планами, обратитесь к администратору кафедры.</p>{/if}
      <div class="account-columns"><div class="account-main">
        {#if departments.length > 1}<section class="account-panel department-panel"><label>Кафедра<select bind:value={departmentId} on:change={loadDepartment}>{#each departments as department}<option value={department.id}>{department.name}</option>{/each}</select></label></section>{/if}
        {#if activeDepartment?.role === 'admin'}
          <section class="account-panel team-panel"><div class="panel-heading"><div><span class="panel-overline">КАФЕДРА</span><h2>Сотрудники <span class="count">{accounts.length}</span></h2><p>Доступ и привязка к расписанию.</p></div><button class="account-primary compact" on:click={() => { showInvite = !showInvite; linkAccount = null; }}>{showInvite ? 'Закрыть' : 'Добавить сотрудника'} <AppIcon name={showInvite ? 'close' : 'plus'} size={17} /></button></div>
            {#if showInvite}<div class="form-well"><h3>Новый сотрудник</h3><p>Выберите преподавателя и создайте ссылку для входа.</p>{#if directoryState !== 'fresh'}<p class="directory-note">Справочник преподавателей {directoryState === 'loading' ? 'загружается' : 'неактуален или недоступен'}. <button on:click={loadDepartment}>Обновить</button></p>{/if}<form class="form-grid" on:submit|preventDefault={invite}><label>Преподаватель<select bind:value={teacherId} required><option value="">Выберите преподавателя</option>{#each teachers as teacher}<option value={String(teacher.lecturerOid)}>{teacher.shortFIO || teacher.fio}</option>{/each}</select></label><label>Имя в приложении<input bind:value={accountName} placeholder="Имя и фамилия" required /></label><label>Электронная почта<input type="email" bind:value={accountEmail} placeholder="name@example.ru" required /></label><label>Роль<select bind:value={role}><option value="planner">Сотрудник</option><option value="viewer">Только просмотр</option></select></label><button class="account-primary compact" disabled={working || directoryState !== 'fresh'}>{working ? 'Создаём…' : 'Создать аккаунт'} <AppIcon name="arrow-up-right" size={17} /></button></form></div>{/if}
            {#if linkAccount}<div class="form-well"><h3>Привязка преподавателя</h3><p>Сотрудник: {linkAccount.display_name}</p><form class="form-grid" on:submit|preventDefault={updateTeacherLink}><label>Преподаватель<select bind:value={replacementTeacherId} required><option value="">Выберите преподавателя</option>{#each teachers as teacher}<option value={String(teacher.lecturerOid)}>{teacher.shortFIO || teacher.fio}</option>{/each}</select></label><div class="form-actions"><button class="account-primary compact" disabled={directoryState !== 'fresh'}>Сохранить</button><button type="button" class="account-quiet" on:click={() => linkAccount = null}>Отмена</button></div></form></div>{/if}
            <div class="list-tools"><label class="search-label"><AppIcon name="search" size={17} /><input bind:value={filter} placeholder="Найти сотрудника" aria-label="Найти сотрудника" /></label><span>{visibleAccounts.length} из {accounts.length}</span></div>
            {#if visibleAccounts.length}<div class="people-list">{#each visibleAccounts as item (item.id)}<details class="person-row"><summary><span class="person-avatar">{item.display_name.trim().slice(0, 1).toUpperCase()}</span><span class="person-main"><strong>{item.display_name}</strong><small>{item.email}</small></span><span class="person-role">{item.role === 'admin' ? 'Администратор' : item.role === 'planner' ? 'Сотрудник' : 'Просмотр'}</span><span class="person-state" class:muted={item.status !== 'active' || !item.activated_at}>{item.status === 'active' ? (item.activated_at ? 'Активен' : 'Ожидает входа') : 'Приостановлен'}</span><span class="person-more" aria-label="Действия">⋯</span></summary><div class="person-actions"><button on:click={() => { linkAccount = item; replacementTeacherId = ''; showInvite = false; }}>Изменить преподавателя</button>{#if item.role === 'planner'}<button on:click={() => toggleOverride(item)}>{item.can_override_source_conflict ? 'Запретить обход конфликта' : 'Разрешить обход конфликта'}</button>{/if}<button on:click={() => reset(item)}>Ссылка для смены пароля</button><button on:click={() => toggle(item)}>{item.status === 'active' ? 'Приостановить доступ' : 'Восстановить доступ'}</button></div></details>{/each}</div>{:else}<div class="empty-state">{filter ? 'По этому запросу сотрудников нет.' : 'Сотрудников пока нет.'}</div>{/if}
          </section>
        {/if}
      </div><aside class="account-side"><section class="account-panel notices-panel"><div class="panel-heading"><div><span class="panel-overline">СОБЫТИЯ</span><h2>Уведомления {#if unread}<span class="count">{unread}</span>{/if}</h2></div><span class="notice-glyph"><AppIcon name="clock" size={21} /></span></div>{#if notices.length}<div class="notice-list">{#each notices as notice (notice.id)}<article class="notice-item" class:notice-read={!!notice.read_at}><span class="notice-dot" aria-hidden="true"></span><div><strong>{notice.kind === 'substitution_confirmed' ? 'Вас назначили на замену' : notice.kind === 'substitution_cancelled' ? 'Замена отменена' : 'Изменилось расписание'}</strong>{#if notice.payload.event_date}<small>{notice.payload.event_date} · пара {notice.payload.slot_number}</small>{/if}{#if !notice.read_at}<button on:click={() => markRead(notice)}>Отметить прочитанным</button>{/if}</div></article>{/each}</div>{:else}<div class="notices-empty"><span aria-hidden="true">·</span><strong>Всё спокойно</strong><p>Здесь появятся замены и изменения расписания.</p></div>{/if}</section><div class="account-side-note"><AppIcon name="info" size={18} /><p>Планы видны сотрудникам кафедры. Изменять их может автор и сотрудники с выданным доступом.</p></div></aside></div>
    {/if}
  {/if}
</div>

<style>
  .account-page{width:min(1420px,calc(100% - 80px));margin:42px auto 90px;color:#1d3c31}.account-kicker,.panel-overline{font-size:11px;font-weight:800;letter-spacing:.13em;color:#448c78}.auth-layout{min-height:610px;display:grid;grid-template-columns:minmax(0,1fr) minmax(380px,480px);align-items:center;gap:clamp(48px,8vw,140px);max-width:1200px;margin:0 auto}.auth-intro h1{font-size:clamp(38px,4vw,62px);line-height:1.08;letter-spacing:-.055em;max-width:640px;margin:20px 0}.auth-intro>p{font-size:16px;line-height:1.7;color:#72877b;max-width:510px}.auth-note{display:flex;gap:15px;align-items:center;margin-top:52px;color:#376c55}.auth-note>span{font-size:26px}.auth-note strong,.auth-note small{display:block}.auth-note small{font-size:13px;color:#82988a;margin-top:5px}.auth-panel,.account-panel{background:#fff;border:1px solid #e1e9df;border-radius:14px}.auth-panel{padding:38px}.auth-panel-top{display:flex;align-items:center;gap:10px;font-size:10px;font-weight:800;letter-spacing:.12em;color:#83a293}.auth-symbol{font-size:21px;color:#3d9378}.auth-panel h2{font-size:27px;letter-spacing:-.04em;margin:30px 0 8px}.auth-panel>p,.account-panel p{font-size:14px;color:#788f80;line-height:1.6}.account-form{display:grid;gap:18px;margin-top:28px}.account-form label,.form-grid label,.department-panel label{display:grid;gap:8px;font-size:13px;font-weight:700;color:#516c5d}.account-page input,.account-page select{min-width:0;width:100%;height:48px;padding:0 14px;border:1px solid #dce8dc;background:#f8faf7;border-radius:8px;color:#264838;font:inherit}.account-page input::placeholder{color:#a5b9aa}.account-page button{font:inherit;cursor:pointer}.account-primary,.account-outline{min-height:48px;display:inline-flex;align-items:center;justify-content:space-between;gap:24px;border-radius:9px;padding:0 18px;font-weight:800;font-size:13px}.account-primary{background:#245f50;color:#fff;border:1px solid #245f50}.account-primary:disabled{opacity:.5;cursor:not-allowed}.account-primary span{font-size:18px}.account-primary.compact{min-height:42px;white-space:nowrap}.account-outline{background:#fff;color:#315f4c;border:1px solid #dbe8dd}.auth-help{font-size:12px!important;margin-top:25px!important}.account-breadcrumb{display:flex;gap:14px;color:#a2b3a5;font-size:12px;font-weight:700}.account-breadcrumb strong{color:#59836c}.profile-header{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:45px 0 34px;border-bottom:1px solid #e1e9df;margin-bottom:28px}.profile-header h1{font-size:clamp(30px,3vw,42px);letter-spacing:-.05em;margin:10px 0 8px}.profile-header p{margin:0;color:#7e9586;font-size:14px}.profile-separator{margin:0 8px;color:#bdd0c0}.account-columns{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:20px;align-items:start}.account-main,.account-side{display:grid;gap:18px}.account-panel{padding:24px}.panel-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.panel-heading h2{font-size:21px;letter-spacing:-.035em;margin:8px 0 0}.panel-heading p{margin:6px 0 0}.count{display:inline-block;padding:4px 8px;margin-left:5px;background:#edf5ed;border-radius:20px;font-size:12px;color:#568c6b;vertical-align:middle;letter-spacing:0}.form-well{margin-top:22px;padding:20px;background:#f5f8f4;border:1px solid #e2eae0;border-radius:10px}.form-well h3{font-size:16px;margin:0}.form-well p{margin:5px 0 0}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:18px}.form-actions{display:flex;align-items:end;gap:8px}.account-quiet,.directory-note button,.person-actions button,.notice-item button{border:0;background:none;color:#31735c;font-weight:700}.account-quiet{min-height:42px}.directory-note{padding:10px 12px;background:#ebf3ed;border-radius:7px}.directory-note button{text-decoration:underline}.list-tools{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:24px 0 8px;color:#9aafa0;font-size:12px;font-weight:700}.search-label{display:flex;align-items:center;gap:8px;width:min(320px,100%);height:40px;padding:0 12px;border:1px solid #e2eae2;background:#f8faf8;border-radius:8px;color:#8da99a}.search-label span{font-size:23px}.search-label input{height:auto;padding:0;border:0;background:none;outline:none;font-size:13px}.person-row{border-top:1px solid #edf1eb}.person-row summary{display:flex;align-items:center;gap:13px;min-height:72px;cursor:pointer;list-style:none}.person-row summary::-webkit-details-marker{display:none}.person-avatar{width:36px;height:36px;flex:none;border-radius:9px;background:#eaf4ea;color:#377458;display:grid;place-items:center;font-weight:800}.person-main{min-width:0;flex:1}.person-main strong,.person-main small{display:block}.person-main strong{font-size:13px}.person-main small{color:#93a79a;font-size:12px;margin-top:5px;overflow:hidden;text-overflow:ellipsis}.person-role,.person-state{font-size:12px;color:#748d7e;white-space:nowrap}.person-state{color:#4e9270}.person-state.muted{color:#a5aca4}.person-more{font-size:22px;color:#789586;padding:0 5px}.person-actions{display:flex;flex-wrap:wrap;gap:8px;padding:0 0 16px 49px}.person-actions button{padding:8px 10px;background:#f2f7f2;border-radius:7px;font-size:12px}.notice-glyph{font-size:22px;color:#79a68b}.notice-list{margin-top:16px}.notice-item{display:flex;gap:10px;padding:14px 0;border-top:1px solid #edf1eb}.notice-dot{width:7px;height:7px;border-radius:50%;background:#55a77b;flex:none;margin-top:5px}.notice-read .notice-dot{background:#d9e4db}.notice-item strong,.notice-item small{display:block;font-size:13px;line-height:1.45}.notice-item small{color:#90a697;margin-top:4px;font-size:12px}.notice-item button{font-size:11px;padding:7px 0 0}.notices-empty{text-align:center;padding:32px 6px 14px}.notices-empty>span{display:grid;place-items:center;margin:auto;width:40px;height:40px;background:#edf6ee;border-radius:12px;color:#5b9b70}.notices-empty strong{display:block;font-size:13px;margin-top:14px}.notices-empty p{margin:5px 0}.account-side-note{display:flex;gap:10px;padding:16px;color:#7e9b87;font-size:12px;line-height:1.5}.account-side-note p{margin:0}.account-alert{padding:12px 15px;border-radius:8px;font-size:13px;margin:0 0 18px}.account-alert.error{background:#fff0ec;color:#944d40}.account-alert.success{background:#edf6ee;color:#2c694f}.invite-result{display:flex;justify-content:space-between;align-items:end;gap:18px;background:#edf6ee;border:1px solid #cde8d2;border-radius:12px;padding:20px;margin-bottom:18px}.invite-result>div{flex:1;min-width:0}.invite-result strong{font-size:14px}.invite-result p{font-size:12px;color:#668d70}.invite-result input{background:#fff;font-size:12px}.empty-state{text-align:center;color:#8a9d90;padding:32px;font-size:13px}@media(max-width:1000px){.account-columns{grid-template-columns:1fr}.account-side{grid-row:1}.notices-empty{text-align:left;padding:15px 0 0}.notices-empty>span{display:none}.auth-layout{gap:40px}}@media(max-width:680px){.account-page{width:calc(100% - 32px);margin-top:25px}.auth-layout{grid-template-columns:1fr;gap:25px;min-height:0}.auth-intro h1{font-size:38px}.auth-intro>p{font-size:14px}.auth-note{margin-top:22px}.auth-panel{padding:24px}.profile-header{padding:30px 0 24px;align-items:start}.profile-header h1{font-size:30px}.account-panel{padding:18px}.panel-heading{align-items:start;flex-direction:column}.form-grid{grid-template-columns:1fr}.person-row summary{flex-wrap:wrap;padding:12px 0;gap:8px}.person-main{min-width:calc(100% - 90px)}.person-role{margin-left:44px}.person-state{margin-left:auto}.person-actions{padding-left:0}.invite-result{align-items:stretch;flex-direction:column}.account-outline{justify-content:center}}

  .auth-layout{max-width:1180px;min-height:560px;grid-template-columns:minmax(0,1fr) minmax(360px,440px);gap:clamp(48px,7vw,110px)}
  .auth-intro h1{font-size:clamp(38px,3.7vw,54px);max-width:570px;line-height:1.12;margin:17px 0 16px}
  .auth-intro>p{font-size:15px;max-width:470px}
  .auth-note{margin-top:34px;padding-top:20px;border-top:1px solid #e3eae2;max-width:470px}
  .auth-note>svg{flex:none;color:#548d70}
  .auth-panel{padding:32px;border-radius:12px;box-shadow:0 16px 38px rgba(34,72,53,.07)}
  .auth-panel h2{font-size:24px;margin:24px 0 7px}
  .auth-panel>p{font-size:13px;margin:0}
  .account-form{gap:16px;margin-top:25px}
  .account-form label{gap:7px;font-size:12px}
  .account-form input{height:50px}
  .auth-panel .account-primary{width:100%;margin-top:3px}
  .auth-help{line-height:1.55!important;margin-top:18px!important}
  .auth-symbol{display:grid;place-items:center;width:42px;height:42px;border:1px solid #dbe8dc;border-radius:9px;color:#4d8d70}
  @media(max-width:1000px){.auth-layout{max-width:850px;grid-template-columns:minmax(0,1fr) minmax(330px,400px);gap:40px}}
  @media(max-width:680px){.auth-layout{grid-template-columns:1fr;gap:20px;max-width:480px}.auth-intro h1{font-size:34px}.auth-intro>p{font-size:14px}.auth-note{margin-top:18px}.auth-panel{padding:24px}}

</style>
