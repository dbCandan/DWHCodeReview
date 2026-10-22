import {withBrowser, baseUrl, accounts, message, signIn, apiStatus} from '../shared/harness.mjs';
import {openAdminSection, openLibrary} from './navigation.mjs';

const STAMP = Date.now();
const MARKER = `E2E geçici kural ${STAMP}: ayrıntılı metin yalnız süper yöneticiye görünür.`;
const SUMMARY = `E2E geçici kural özeti ${STAMP}.`;

/**
 * rule-management Acceptance 4 and directory-login Acceptance 2 and Decision 14 (local): the super
 * admin adds a rule with its one-sentence summary, saves and publishes the next version; a user
 * cannot open the rules page, gets 403 from the draft endpoint and reads the new version as one
 * sentence per rule. The scenario removes its rule and publishes again in `finally`.
 */
await withBrowser('rules edit and publish by the super admin, users read-only', async ({page, assert, newPage}) => {
  await signIn(page, accounts.superAdmin);
  const admin = await newPage();
  await signIn(admin, accounts.superAdmin);
  let added = false;
  try {
    await openAdminSection(page, 'Kurallar');
    const before = await apiStatus(page, '/rule-set');
    assert.equal(before.status, 200);
    const previous = before.body.latest_version.number;
    await page.getByText(`Son yayın: sürüm ${previous}`).waitFor();

    await page.getByRole('button', {name: 'Normal grubuna kural ekle'}).click();
    const newId = before.body.next_rule_id;
    await page.getByLabel(`${newId} kural metni`).fill(MARKER);
    await page.getByLabel(`${newId}: Özet (tek cümle)`).fill(SUMMARY);
    await page.getByText('Kaydedilmedi').waitFor();
    await page.getByRole('button', {name: 'Taslağı kaydet'}).click();
    await page.getByText('Taslak kaydedildi.').waitFor();
    added = true;
    await page.getByText('Taslakta yayımlanmamış değişiklik var').waitFor();

    // directory-login Decision 14: there is no approval step for the super admin's own draft.
    assert.equal(await page.getByRole('button', {name: 'Onaya gönder'}).count(), 0);
    await page.getByRole('button', {name: 'Yayınla'}).click();
    await page.getByText(`Sürüm ${previous + 1} yayımlandı.`, {exact: false}).waitFor();
    const latest = await apiStatus(page, '/rule-set/versions/latest');
    assert.equal(latest.body.number, previous + 1);
    assert.equal(latest.body.normal.at(-1).summary, SUMMARY);

    await page.reload();
    await page.getByText(`Son yayın: sürüm ${previous + 1}`).waitFor();

    // Reviewer: no rules menu item, forbidden page, 403 from the draft endpoint, one-sentence view.
    const reviewer = await newPage();
    await signIn(reviewer, accounts.reviewer);
    const nav = reviewer.getByRole('navigation', {name: message('shell.navigation')});
    assert.equal(await nav.getByRole('link', {name: 'Kurallar', exact: true}).count(), 0);
    assert.equal(await nav.getByRole('link', {name: 'Yönetim', exact: true}).count(), 0);
    await reviewer.goto(baseUrl + '/kurallar');
    await reviewer.getByRole('heading', {name: message('access.forbidden.title')}).waitFor();
    const draft = await apiStatus(reviewer, '/rule-set');
    assert.equal(draft.status, 403);
    assert.equal(draft.body.detail.code, 'forbidden');

    await openLibrary(reviewer, 'Yayımlanmış kurallar');
    await reviewer.getByText(SUMMARY).waitFor();
    assert.equal(await reviewer.getByText(MARKER).count(), 0);
    await reviewer.getByText(new RegExp(`^Sürüm ${previous + 1} · .* · yayımlayan: `)).waitFor();
    assert.equal(await reviewer.getByRole('textbox', {name: /kural metni/}).count(), 0);
    assert.equal(await reviewer.getByRole('button', {name: 'Yayınla'}).count(), 0);
  } finally {
    if (added) {
      // Clean up through the public API: remove the rule; the super admin publishes again.
      const current = await apiStatus(page, '/rule-set');
      const normal = current.body.normal.filter((rule) => rule.text !== MARKER);
      const saved = await apiStatus(page, '/rule-set/draft', {
        method: 'PUT',
        body: {base_revision: current.body.revision, critical: current.body.critical, normal, groups: current.body.groups},
      });
      assert.equal(saved.status, 200);
      const published = await apiStatus(admin, '/rule-set/versions', {
        method: 'POST',
        body: {base_revision: saved.body.revision},
      });
      assert.ok([200, 201].includes(published.status));
    }
  }
});
