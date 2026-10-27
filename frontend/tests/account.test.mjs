import assert from 'node:assert/strict';
import { get } from 'svelte/store';

const values = new Map();
globalThis.sessionStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value),
  removeItem: (key) => values.delete(key)
};
const { account, mayPlan, restoreAccount, setAccount } = await import('../src/lib/account.ts');
const user = { id: '1', display_name: 'Тест', email: 'test@example.invalid' };
const department = { id: '2', name: 'ПМиФИ', role: 'planner', source_chair_oid: '46' };
const session = { token: 'test-token', user, departments: [department], departmentId: '2' };

assert.equal(mayPlan(null), false);
assert.equal(mayPlan({ ...session, departments: [{ ...department, role: 'viewer' }] }), false);
assert.equal(mayPlan(session), true);
setAccount(session);
account.set(null);
globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => url.endsWith('/auth/me') ? user : [department] });
await restoreAccount();
assert.equal(get(account).user.display_name, 'Тест');
assert.equal(mayPlan(get(account)), true);
globalThis.fetch = async () => { throw new Error('network'); };
await restoreAccount();
assert.equal(get(account), null);
assert.equal(values.size, 1, 'temporary network error retains the saved session');
globalThis.fetch = async () => ({ ok: false, status: 401 });
await restoreAccount();
assert.equal(get(account), null);
assert.equal(values.size, 0, 'expired session is removed');
setAccount(session);
let callbacks = [];
globalThis.fetch = () => new Promise((resolve) => callbacks.push(resolve));
const staleRestore = restoreAccount();
setAccount(null);
for (const resolve of callbacks) resolve({ ok: true, status: 200, json: async () => [] });
await staleRestore;
assert.equal(get(account), null, 'logout is not undone by an in-flight restore');
console.log('Account navigation and session checks passed');
