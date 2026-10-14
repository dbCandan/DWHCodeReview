import {withBrowser, baseUrl, accounts, message, signIn, apiStatus} from '../shared/harness.mjs';

const STAMP = Date.now();
const MARKER = `E2E geçici kural ${STAMP}: ayrıntılı metin yalnız süper yöneticiye görünür.`;
const SUMMARY = `E2E geçici kural özeti ${STAMP}.`;

async function openApprovals(admin) {
  await admin.getByRole('navigation', {name: message('shell.navigation')}).getByRole('link', {name: /Kural onayları/}).click();
  await admin.getByRole('heading', {name: 'Kural onayları', level: 1}).waitFor();
}

/**
 * rule-management Acceptance 4, rule-proposals Decision 3 and directory-login Acceptance 2
 * (local): the rule manager adds a rule with its one-sentence summary, saves and sends the draft
 * for approval (a direct publish is refused); the super admin sees the difference and approves,
 * which publishes the next version; the reviewer cannot open the rules page, gets 403 from the
 * draft endpoint and reads the new version as one sentence per rule. The scenario removes its
 * rule and publishes again through the super admin in `finally`.
 */
await withBrowser('rules edit, approval and publish, reviewer read-only', async ({page, assert, newPage}) => {
  await signIn(page, accounts.ruleManager);
  const admin = await newPage();
  await signIn(admin, accounts.superAdmin);
  let added = false;
  try {
    await page.getByRole('navigation', {name: message('shell.navigation')}).getByRole('link', {name: 'Kurallar', exact: true}).click();
    await page.getByRole('heading', {name: 'Kurallar', level: 1}).waitFor();
    const before = await apiStatus(page, '/rule-set');
    assert.equal(before.status, 200);
    const previous = before.body.latest_version.number;
    await page.getByText(`Son yayın: sürüm ${previous}`).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Yayınla'}).count(), 0);

    await page.getByRole('button', {name: 'Normal grubuna kural ekle'}).click();
    const newId = before.body.next_rule_id;
    await page.getByLabel(`${newId} kural metni`).fill(MARKER);
    await page.getByLabel(`${newId}: Özet (tek cümle)`).fill(SUMMARY);
    await page.getByText('Kaydedilmedi').waitFor();
    await page.getByRole('button', {name: 'Taslağı kaydet'}).click();
    await page.getByText('Taslak kaydedildi.').waitFor();
    added = true;
    await page.getByText('Taslakta yayımlanmamış değişiklik var').waitFor();

    // rule-proposals Decision 3: the rule manager cannot publish directly.
    const direct = await apiStatus(page, '/rule-set/versions', {
      method: 'POST',
      body: {base_revision: (await apiStatus(page, '/rule-set')).body.revision},
    });
    assert.equal(direct.status, 403);
    assert.equal(direct.body.detail.code, 'publish_requires_approval');

    await page.getByRole('button', {name: 'Onaya gönder'}).click();
    await page.getByText('Taslak onaya gönderildi. Süper yönetici onaylayınca yeni sürüm yayımlanır.').waitFor();
    await page.getByText('Son yayın isteği: onay bekliyor').waitFor();

    // Super admin: the difference shows the new rule with its detailed text; approval publishes.
    await openApprovals(admin);
    await admin.getByRole('tab', {name: /^Yayın istekleri/}).click();
    const added_rules = admin.getByRole('region', {name: 'Eklenen kurallar'}).first();
    await added_rules.getByText(MARKER).waitFor();
    await admin.getByRole('button', {name: 'Yayın isteği onayla'}).first().click();
    await admin.getByText('Bekleyen yayın isteği yok').waitFor();
    const latest = await apiStatus(page, '/rule-set/versions/latest');
    assert.equal(latest.body.number, previous + 1);
    assert.equal(latest.body.normal.at(-1).summary, SUMMARY);

    await page.reload();
    await page.getByText(`Son yayın: sürüm ${previous + 1}`).waitFor();
    await page.getByText(/Son yayın isteği: onaylandı · sürüm/).waitFor();

    // Reviewer: no rules menu item, forbidden page, 403 from the draft endpoint, one-sentence view.
    const reviewer = await newPage();
    await signIn(reviewer, accounts.reviewer);
    const nav = reviewer.getByRole('navigation', {name: message('shell.navigation')});
    assert.equal(await nav.getByRole('link', {name: 'Kurallar', exact: true}).count(), 0);
    await reviewer.goto(baseUrl + '/kurallar');
    await reviewer.getByRole('heading', {name: message('access.forbidden.title')}).waitFor();
    const draft = await apiStatus(reviewer, '/rule-set');
    assert.equal(draft.status, 403);
    assert.equal(draft.body.detail.code, 'forbidden');

    await nav.getByRole('link', {name: 'Yayımlanmış kurallar'}).click();
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
