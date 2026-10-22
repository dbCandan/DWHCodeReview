import {withBrowser, baseUrl, accounts, signIn, apiStatus} from '../shared/harness.mjs';
import {openReview} from './navigation.mjs';

/**
 * scheduled-review-email Acceptance 4 and review-history-export Acceptance 6 (local L2). The
 * reviewer defines a scheduled review on the page, pauses and resumes it; the super admin runs it
 * now and the backend scheduler (DWHCODEREVIEW_SCHEDULER_ENABLED=true) runs it in the background.
 * With `APP_E2E_LLM_BASE_URL` and `APP_E2E_SQL_OBJECT` ("DATABASE.schema.name:TYPE", an object of
 * the test SQL Server) the run completes: the report is stored, the owner opens it through the
 * e-mail link, a user who was not a recipient of that run gets 404, and after the second reviewer
 * is added as a recipient the next run opens for them read-only. The summary e-mail state is
 * "sent" with a test relay and "not configured" without one; its content (no code snippet) is
 * checked in the relay's mailbox, outside this script. Without those variables the run is
 * expected to end with a stable error code instead. The backend must allow the local accounts'
 * e-mail domain in DWHCODEREVIEW_MAIL_ALLOWED_DOMAINS. The definition and its runs are deleted in
 * `finally`.
 */
const llmBaseUrl = process.env.APP_E2E_LLM_BASE_URL || '';
const objectSpec = process.env.APP_E2E_SQL_OBJECT || '';
const NAME = `e2e-zamanli-${Date.now()}`;
const FINISHED = new Set(['completed', 'failed', 'cancelled', 'interrupted', 'skipped']);

function selection() {
  const match = /^([^.]+)\.([^.]+)\.([^:]+):([A-Z]{1,2})$/.exec(objectSpec);
  if (!match) return {mode: 'filter', filter: {database: 'DWH'}};
  const [, database, schema, name, typeCode] = match;
  return {mode: 'list', items: [{database, schema, name, type_code: typeCode}]};
}

async function emailOf(admin, account) {
  const users = await apiStatus(admin, '/admin/users?page=1&size=200');
  const user = users.body.items.find((item) => item.username === account.username);
  if (!user) throw new Error(`account ${account.username} is not listed`);
  return user.email;
}

/** The scheduler ticks once a minute; a real model answers each rule in turn. */
async function finishedRun(page, scheduleId, previous, assert) {
  const deadline = Date.now() + 900_000;
  while (Date.now() < deadline) {
    const runs = await apiStatus(page, `/scheduled-reviews/${scheduleId}/runs`);
    assert.equal(runs.status, 200);
    const fresh = runs.body.items.filter((item) => !previous.includes(item.id));
    const done = fresh.find((item) => FINISHED.has(item.state));
    if (done) return done;
    await page.waitForTimeout(5_000);
  }
  throw new Error('the scheduled run did not finish in time');
}

await withBrowser('scheduled review: define, run in the background, open the report from the e-mail link', async ({page, assert, newPage}) => {
  const admin = page;
  await signIn(admin, accounts.superAdmin);
  const owner = await newPage();
  await signIn(owner, accounts.reviewer);
  const other = await newPage();
  await signIn(other, accounts.secondReviewer);
  const ownerEmail = await emailOf(admin, accounts.reviewer);
  const otherEmail = await emailOf(admin, accounts.secondReviewer);
  let scheduleId = null;
  const runIds = [];
  try {
    const body = {
      name: NAME,
      selection: selection(),
      rule_group_ids: [],
      period: {frequency: 'daily', hour: 3, minute: 0, timezone: 'Europe/Istanbul'},
      recipients: [ownerEmail],
    };
    const created = await apiStatus(owner, '/scheduled-reviews', {method: 'POST', body});
    assert.equal(created.status, 201, `create answered ${created.status} ${created.body?.detail?.code ?? ''}`);
    scheduleId = created.body.id;

    // The page lists the definition with its period; pause and resume change its state.
    await openReview(owner, 'Zamanlanmış', 'Zamanlanmış incelemeler');
    const row = owner.getByRole('article', {name: NAME});
    await row.getByText('Her gün 03:00 (Europe/Istanbul)').waitFor();
    await owner.getByRole('button', {name: `${NAME} tanımını duraklat`}).click();
    await owner.getByText('Tanım duraklatıldı.').waitFor();
    await row.getByText('Duraklatıldı').waitFor();
    await owner.getByRole('button', {name: `${NAME} tanımını etkinleştir`}).click();
    await owner.getByText('Tanım etkinleştirildi.').waitFor();
    assert.equal(await owner.getByRole('button', {name: `${NAME} şimdi çalıştır`}).count(), 0);
    assert.equal((await apiStatus(other, `/scheduled-reviews/${scheduleId}`)).status, 404);

    // The super admin sees every definition and runs this one now.
    await admin.goto(baseUrl + '/zamanlanmis-incelemeler');
    await admin.getByRole('button', {name: `${NAME} şimdi çalıştır`}).click();
    await admin.getByText('Koşum sıraya alındı.').waitFor();
    const first = await finishedRun(owner, scheduleId, [], assert);

    if (!llmBaseUrl || !objectSpec) {
      assert.equal(first.state, 'failed');
      assert.equal(first.trigger, 'manual');
      console.log('NOTE APP_E2E_LLM_BASE_URL or APP_E2E_SQL_OBJECT not set: verified definition, pause, run now and a failed background run only');
      return;
    }

    assert.equal(first.state, 'completed');
    assert.ok(['sent', 'not_configured'].includes(first.email_status), first.email_status);
    runIds.push(first.review_run_id);
    // The e-mail link opens the report for the owner; the second reviewer was no recipient.
    await owner.goto(`${baseUrl}/gecmis?run=${first.review_run_id}`);
    await owner.getByText('Zamanlanmış', {exact: true}).first().waitFor();
    assert.equal((await apiStatus(other, `/review-runs/${first.review_run_id}`)).status, 404);

    // Adding a recipient affects the next run only (review-history-export Decision 8).
    const updated = await apiStatus(owner, `/scheduled-reviews/${scheduleId}`, {
      method: 'PUT',
      body: {...body, recipients: [ownerEmail, otherEmail]},
    });
    assert.equal(updated.status, 200);
    const queued = await apiStatus(admin, `/scheduled-reviews/${scheduleId}/run`, {method: 'POST'});
    assert.equal(queued.status, 202);
    const second = await finishedRun(owner, scheduleId, [first.id], assert);
    assert.equal(second.state, 'completed');
    runIds.push(second.review_run_id);

    await other.goto(`${baseUrl}/gecmis?run=${second.review_run_id}`);
    await other.getByText('Bu inceleme başka bir kullanıcıya ait; yalnız okunabilir.').waitFor();
    assert.equal(await other.getByRole('checkbox', {name: /yanlış pozitif/}).count(), 0);
    assert.equal((await apiStatus(other, `/review-runs/${second.review_run_id}/exports/csv`)).status, 200);
    assert.equal((await apiStatus(other, `/review-runs/${second.review_run_id}`, {method: 'DELETE'})).status, 404);
    assert.equal((await apiStatus(other, `/review-runs/${first.review_run_id}`)).status, 404);
  } finally {
    for (const runId of runIds) await apiStatus(owner, `/review-runs/${runId}`, {method: 'DELETE'});
    if (scheduleId) {
      const removed = await apiStatus(owner, `/scheduled-reviews/${scheduleId}`, {method: 'DELETE'});
      assert.ok([204, 404].includes(removed.status), `delete answered ${removed.status}`);
    }
  }
}, {
  // "İnceleme" opens the object review first; the unconfigured SQL Server answers its database
  // list with 503 by contract before the switch moves to the scheduled reviews.
  expectedServerErrors: [/^503 GET .*\/api\/dwhcodereview\/v1\/databases\?/],
});
