import { writable } from 'svelte/store';

export type DepartmentAccess = { id: string; name: string; role: 'admin' | 'planner' | 'viewer'; source_chair_oid: string | null };
export type AccountSession = { token: string; user: { id: string; display_name: string; email: string }; departments: DepartmentAccess[]; departmentId: string };

export function mayPlan(session: AccountSession | null): boolean {
  const role = session?.departments.find((item) => item.id === session.departmentId)?.role;
  return role === 'admin' || role === 'planner';
}

const storageKey = 'zapara-session-v1';
let sessionEpoch = 0;
export const account = writable<AccountSession | null>(null);
export const accountChecking = writable(false);
export const unreadNotifications = writable(0);

export function setAccount(session: AccountSession | null) {
  sessionEpoch += 1;
  account.set(session);
  if (!session) unreadNotifications.set(0);
  try {
    if (session) sessionStorage.setItem(storageKey, JSON.stringify(session));
    else sessionStorage.removeItem(storageKey);
  } catch { /* The session remains available in this tab until refresh. */ }
}

export async function restoreAccount() {
  let previous: AccountSession | null = null;
  try { previous = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); } catch { /* Invalid local state. */ }
  if (!previous?.token) return;
  accountChecking.set(true);
  const epoch = sessionEpoch;
  try {
    const headers = { Authorization: `Bearer ${previous.token}` };
    const [userResponse, departmentResponse] = await Promise.all([
      fetch('/backend-api/auth/me', { headers }),
      fetch('/backend-api/admin/departments', { headers })
    ]);
    if (epoch !== sessionEpoch) return;
    if (userResponse.status === 401 || departmentResponse.status === 401) { setAccount(null); return; }
    if (!userResponse.ok || !departmentResponse.ok) { account.set(null); return; }
    const [user, departments] = await Promise.all([userResponse.json(), departmentResponse.json()]);
    if (epoch !== sessionEpoch) return;
    const departmentId = departments.some((d: DepartmentAccess) => d.id === previous?.departmentId) ? previous.departmentId : departments[0]?.id || '';
    setAccount({ token: previous.token, user, departments, departmentId });
    const activeEpoch = sessionEpoch;
    try {
      const notices = await fetch('/backend-api/notifications', { headers });
      if (notices.ok) {
        const items = await notices.json();
        if (activeEpoch === sessionEpoch) unreadNotifications.set(items.filter((item: { read_at: string | null }) => !item.read_at).length);
      }
    } catch { /* Notification state will be refreshed on the next check. */ }
  } catch { if (epoch === sessionEpoch) account.set(null); }
  finally { accountChecking.set(false); }
}
