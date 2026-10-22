import {withBrowser, baseUrl, accounts, signIn, apiStatus, apiPrefix, sessionToken} from '../shared/harness.mjs';
import {mainMenu, openAdminSection, openLibrary, openReview} from './navigation.mjs';

/**
 * rule-group-selection Acceptance 4 (local): the rule manager defines two named groups, puts one
 * new rule into both and another into one, and publishes; the reviewer sees the groups on the
 * published-rules page and on the script review page, ticks a group and one more single rule, and
 * gets exactly those rules once, each labelled with all of its groups; a run with nothing selected
 * runs every rule. Like
 * 02-script-review-history, `APP_E2E_LLM_BASE_URL` names the LLM endpoint; without it only the
 * rule-side steps and the "not configured" refusal are checked. The scenario removes its rules and
 * groups, publishes the original content again, restores the LLM settings and deletes its runs in
 * `finally`.
 */
const llmBaseUrl = process.env.APP_E2E_LLM_BASE_URL || '';
const llmModel = process.env.APP_E2E_LLM_MODEL || 'e2e-model';
const STAMP = Date.now();
const GROUP_A = `E2E Güvenlik ${STAMP}`;
const GROUP_B = `E2E Performans ${STAMP}`;
const RULE_A = `E2E grup kuralı A ${STAMP}: NOLOCK kullanılmamalıdır.`;
const RULE_B = `E2E grup kuralı B ${STAMP}: SELECT * kullanılmamalıdır.`;
const LABEL_GROUP = `e2e-grup-${STAMP}`;
const LABEL_ALL = `e2e-tum-${STAMP}`;
const SQL = ['CREATE PROCEDURE dbo.e2e_group AS', 'BEGIN', '  SELECT *', '  FROM #kaynak WITH (NOLOCK);', 'END'].join('\n');

function formatRuleId(value) {
  return value < 100 ? `Kural${String(value).padStart(2, '0')}` : `Kural${value}`;
}

async function openScriptPage(page) {
  await openReview(page, 'SQL betiği', 'SQL betiği incelemesi');
}

async function addGroup(page, index, name) {
  await page.getByRole('button', {name: 'Kural grubu ekle'}).click();
  await page.getByLabel(`Kural grubu ${index} adı`).fill(name);
}

async function addRule(page, ruleId, text, groupNames) {
  await page.getByRole('button', {name: 'Normal grubuna kural ekle'}).click();
  await page.getByLabel(`${ruleId} kural metni`).fill(text);
  const groups = page.getByRole('group', {name: `${ruleId}: Kural grupları`});
  for (const name of groupNames) await groups.getByLabel(name, {exact: true}).check();
}

async function exportText(page, path) {
  const {token, tenant} = await sessionToken(page);
  return page.evaluate(
    async ({url, token, tenant}) => {
      const response = await fetch(url, {headers: {Authorization: 'Bearer ' + token, 'x-tenant-id': tenant}});
      return {status: response.status, text: await response.text()};
    },
    {url: apiPrefix + path, token, tenant},
  );
}

/** The checkbox of the row whose rule code is exactly ruleId (text match, no regular expression). */
function ruleBox(page, ruleId) {
  return page
    .locator('label.option-row')
    .filter({has: page.getByText(ruleId, {exact: true})})
    .getByRole('checkbox');
}

async function finishedRun(page, label) {
  const runs = (await apiStatus(page, '/review-runs?scope=mine&page_size=200')).body.items;
  const run = runs.find((item) => item.title === label);
  if (!run) throw new Error(`run ${label} was not stored`);
  return (await apiStatus(page, `/review-runs/${run.id}`)).body;
}

function ruleIdsOf(detail) {
  return detail.results.flatMap((result) => result.rule_results.map((rule) => rule.rule_id));
}

await withBrowser('rule groups: define, publish, review with a group plus a rule and with every rule', async ({page, assert, newPage}) => {
  const manager = page;
  await signIn(manager, accounts.superAdmin);
  const previousLlm = (await apiStatus(manager, '/llm-connection')).body;
  const reviewer = await newPage();
  await signIn(reviewer, accounts.reviewer);
  const admin = await newPage();
  await signIn(admin, accounts.superAdmin);
  let changed = false;
  try {
    // Super admin: two groups, rule A in both and rule B in the second, save and publish.
    await openAdminSection(manager, 'Kurallar');
    const before = await apiStatus(manager, '/rule-set');
    assert.equal(before.status, 200);
    const previousVersion = before.body.latest_version.number;
    const groupCount = before.body.groups.length;
    await addGroup(manager, groupCount + 1, GROUP_A);
    await addGroup(manager, groupCount + 2, GROUP_B);
    const ruleA = before.body.next_rule_id;
    await addRule(manager, ruleA, RULE_A, [GROUP_A, GROUP_B]);
    // The page numbers new rules one after another from next_rule_id.
    const ruleB = formatRuleId(Number(ruleA.replace('Kural', '')) + 1);
    await addRule(manager, ruleB, RULE_B, [GROUP_B]);
    await manager.getByRole('button', {name: 'Taslağı kaydet'}).click();
    await manager.getByText('Taslak kaydedildi.').waitFor();
    changed = true;
    // directory-login Decision 14: the super admin publishes the draft directly.
    await manager.getByRole('button', {name: 'Yayınla'}).click();
    await manager.getByText(`Sürüm ${previousVersion + 1} yayımlandı.`, {exact: false}).waitFor();

    const published = (await apiStatus(manager, '/rule-set/versions/latest')).body;
    const groupA = published.groups.find((group) => group.name === GROUP_A);
    const groupB = published.groups.find((group) => group.name === GROUP_B);
    assert.ok(groupA && groupB, 'both groups are frozen in the new version');
    const publishedRules = [...published.critical, ...published.normal];
    const allRuleIds = publishedRules.map((rule) => rule.id);
    const membersOf = (group) => publishedRules.filter((rule) => rule.rule_group_ids.includes(group.id)).map((rule) => rule.id);
    assert.deepEqual(membersOf(groupA), [ruleA]);
    assert.deepEqual(membersOf(groupB), [ruleA, ruleB]);
    // A critical rule outside both groups, picked one by one below.
    const single = published.critical.find((rule) => rule.rule_group_ids.length === 0)?.id;
    assert.ok(single, 'the version keeps an ungrouped critical rule');

    // Reviewer: the groups are listed on the published-rules page and offered on the review page.
    const nav = mainMenu(reviewer);
    await openLibrary(reviewer, 'Yayımlanmış kurallar');
    const shelves = reviewer.getByRole('navigation', {name: 'Kural grupları'});
    await shelves.getByRole('button', {name: new RegExp(GROUP_A)}).waitFor();
    await shelves.getByRole('button', {name: new RegExp(GROUP_B)}).click();
    // The chosen group's rules run top to bottom on the right.
    await reviewer.getByRole('region', {name: GROUP_B}).getByRole('heading', {name: GROUP_B}).waitFor();

    await openScriptPage(reviewer);
    await reviewer.getByText('Hiçbir kural seçilmezse tüm kurallar çalışır.').waitFor();
    await reviewer.getByLabel(`${GROUP_A} (1 kural)`).waitFor();
    await reviewer.getByLabel(`${GROUP_B} (2 kural)`).waitFor();

    if (!llmBaseUrl) {
      await reviewer.getByLabel(`${GROUP_A} (1 kural)`).check();
      await reviewer.getByLabel('SQL').fill(SQL);
      await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
      const live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
      await live.getByRole('alert').filter({hasText: 'LLM bağlantısı yapılandırılmamış.'}).waitFor();
      console.log('NOTE APP_E2E_LLM_BASE_URL not set: verified groups and the not-configured refusal only');
      return;
    }

    await manager.goto(baseUrl + '/ayarlar/llm');
    await manager.getByLabel('İstek biçimi').selectOption('openai');
    await manager.getByLabel('Temel adres').fill(llmBaseUrl);
    await manager.getByLabel('Sohbet adresi (isteğe bağlı)').fill('');
    await manager.getByLabel('Model').fill(llmModel);
    await manager.getByRole('button', {name: 'Kaydet'}).click();
    await manager.getByText('LLM bağlantı ayarları kaydedildi.').waitFor();

    // A group or a rule the published version does not have is refused before any LLM call.
    for (const [body, code] of [
      [{rule_group_ids: ['e2e-olmayan-grup']}, 'rule_group_unknown'],
      [{rule_codes: ['Kural9999']}, 'rule_unknown'],
    ]) {
      const refused = await apiStatus(reviewer, '/script-reviews', {method: 'POST', body: {sql: SQL, ...body}});
      assert.equal(refused.status, 422);
      assert.equal(refused.body.detail.code, code);
    }

    // Group A ticked at once plus one single rule: exactly those rules run, each once.
    await reviewer.getByLabel(`${GROUP_A} (1 kural)`).check();
    // The ungrouped rule is found with the search, which lists matches as one list.
    await reviewer.getByLabel('Kural ara').fill(single);
    await ruleBox(reviewer, single).check();
    await reviewer.getByLabel('Kural ara').fill('');
    await reviewer.getByText(`2 / ${allRuleIds.length} kural seçildi.`).waitFor();
    await reviewer.getByLabel('Sonuçlarda görünecek ad (isteğe bağlı)').fill(LABEL_GROUP);
    await reviewer.getByLabel('SQL').fill(SQL);
    await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
    let live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
    await live.getByText('İnceleme tamamlandı.').waitFor({timeout: 900_000});
    await live.getByRole('button', {name: 'Sonuçları göster'}).click();
    const results = reviewer.getByRole('dialog', {name: 'İnceleme sonuçları'});
    // Rule A carries both of its groups; the group filter narrows the list to it.
    await results.getByLabel('Kural grubu').selectOption({label: GROUP_B});
    const shown = results.locator('.rule-line > .row > .mono');
    assert.deepEqual(await shown.allTextContents(), [ruleA]);
    await results.locator('.rule-line').filter({hasText: ruleA}).getByText(GROUP_A, {exact: true}).waitFor();
    await results.getByRole('button', {name: 'Kapat'}).click();

    const grouped = await finishedRun(reviewer, LABEL_GROUP);
    assert.equal(grouped.all_rules, false);
    assert.deepEqual(grouped.selected_rule_groups, []);
    assert.deepEqual(grouped.selected_rule_codes, [single, ruleA]);
    assert.deepEqual(ruleIdsOf(grouped), [single, ruleA]);
    const resultA = grouped.results[0].rule_results.find((rule) => rule.rule_id === ruleA);
    assert.deepEqual(resultA.rule_group_names, [GROUP_A, GROUP_B]);

    // The history detail and the CSV carry the selection and every group name as well.
    await nav.getByRole('link', {name: 'Geçmiş'}).click();
    await reviewer.getByRole('button', {name: new RegExp(`^${LABEL_GROUP} — Tamamlandı`)}).click();
    await reviewer.getByText(`Seçilen kurallar: ${single}, ${ruleA}`).waitFor();
    const csv = await exportText(reviewer, `/review-runs/${grouped.id}/exports/csv`);
    assert.equal(csv.status, 200);
    assert.ok(csv.text.includes(`${GROUP_A}; ${GROUP_B}`), 'the CSV joins the groups with "; "');

    // Nothing selected: every rule of the version runs and the run says so.
    await openScriptPage(reviewer);
    await reviewer.getByLabel(`${GROUP_A} (1 kural)`).waitFor();
    assert.equal(await reviewer.getByLabel(`${GROUP_A} (1 kural)`).isChecked(), false);
    // The ungrouped rule sits in the closed 'Grupsuz' group, which is not ticked either.
    assert.equal(await reviewer.getByLabel(/^Grupsuz \(\d+ kural\)$/).isChecked(), false);
    await reviewer.getByLabel('Sonuçlarda görünecek ad (isteğe bağlı)').fill(LABEL_ALL);
    await reviewer.getByLabel('SQL').fill(SQL);
    await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
    live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
    await live.getByText('İnceleme tamamlandı.').waitFor({timeout: 900_000});
    await live.getByRole('button', {name: 'Kapat'}).click();
    const everything = await finishedRun(reviewer, LABEL_ALL);
    assert.equal(everything.all_rules, true);
    assert.deepEqual(everything.selected_rule_groups, []);
    assert.deepEqual(everything.selected_rule_codes, []);
    assert.deepEqual([...ruleIdsOf(everything)].sort(), [...allRuleIds].sort());
  } finally {
    const runs = await apiStatus(reviewer, '/review-runs?scope=mine&page_size=200');
    for (const item of runs.body?.items ?? []) {
      if ([LABEL_GROUP, LABEL_ALL].includes(item.title)) await apiStatus(reviewer, `/review-runs/${item.id}`, {method: 'DELETE'});
    }
    if (changed) {
      // Remove the scenario's rules and groups and publish the original content again.
      const current = await apiStatus(manager, '/rule-set');
      const ours = new Set(current.body.groups.filter((group) => [GROUP_A, GROUP_B].includes(group.name)).map((group) => group.id));
      const keep = (rule) => ![RULE_A, RULE_B].includes(rule.text);
      const saved = await apiStatus(manager, '/rule-set/draft', {
        method: 'PUT',
        body: {
          base_revision: current.body.revision,
          critical: current.body.critical.filter(keep),
          normal: current.body.normal.filter(keep),
          groups: current.body.groups.filter((group) => !ours.has(group.id)),
        },
      });
      assert.equal(saved.status, 200);
      const republished = await apiStatus(admin, '/rule-set/versions', {
        method: 'POST',
        body: {base_revision: saved.body.revision},
      });
      assert.ok([200, 201].includes(republished.status));
    }
    if (llmBaseUrl && previousLlm.editable) {
      const restored = await apiStatus(manager, '/llm-connection', {
        method: 'PUT',
        body: {
          chat_api: previousLlm.chat_api,
          base_url: previousLlm.base_url ?? '',
          chat_url: previousLlm.chat_url ?? '',
          model: previousLlm.model,
        },
      });
      assert.equal(restored.status, 200);
    }
  }
}, {
  // "İnceleme" opens the object review first; without a SQL Server connection its database list
  // answers 503 by contract before the switch moves to the script review.
  expectedServerErrors: [
    /^503 GET .*\/api\/dwhcodereview\/v1\/databases\?/,
    ...(llmBaseUrl ? [] : [/^503 POST .*\/api\/dwhcodereview\/v1\/script-reviews$/]),
  ],
});
