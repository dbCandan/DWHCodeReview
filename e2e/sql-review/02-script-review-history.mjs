import {expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {withBrowser, baseUrl, accounts, message, signIn, apiStatus} from '../shared/harness.mjs';

/**
 * script-review Acceptance 4-5 and review-history-export Acceptance 4-5 on the local stack.
 * `APP_E2E_LLM_BASE_URL` names an OpenAI-compatible endpoint the backend can reach; the rule
 * manager enters it on the LLM connection page (local only). Without it the scenario checks the
 * "not configured" refusal instead of a completed review. The previous LLM settings are restored
 * and the created runs are deleted in `finally`.
 */
const llmBaseUrl = process.env.APP_E2E_LLM_BASE_URL || '';
const llmModel = process.env.APP_E2E_LLM_MODEL || 'e2e-model';
const LABEL = `e2e-betik-${Date.now()}`;
// Line 4 reads a temp table WITH (NOLOCK): a real Kural01 violation, so a real model reports it too.
const SQL = ['CREATE PROCEDURE dbo.e2e_load AS', 'BEGIN', '  SELECT id', '  FROM #kaynak WITH (NOLOCK);', 'END'].join('\n');

async function openScriptPage(page) {
  await page.getByRole('navigation', {name: message('shell.navigation')}).getByRole('link', {name: 'SQL betiği incelemesi'}).click();
  await page.getByRole('heading', {name: 'SQL betiği incelemesi', level: 1}).waitFor();
}

await withBrowser('script review, live progress, stop, history and exports', async ({page, assert, newPage}) => {
  const manager = page;
  await signIn(manager, accounts.ruleManager);
  const previous = (await apiStatus(manager, '/llm-connection')).body;
  const reviewer = await newPage();
  await signIn(reviewer, accounts.reviewer);
  try {
    if (!llmBaseUrl) {
      await openScriptPage(reviewer);
      await reviewer.getByLabel('SQL').fill(SQL);
      await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
      const live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
      await live.getByRole('alert').filter({hasText: 'LLM bağlantısı yapılandırılmamış.'}).waitFor();
      console.log('NOTE APP_E2E_LLM_BASE_URL not set: verified the not-configured refusal only');
      return;
    }

    // Rule manager points the running backend at the LLM endpoint (local environment only).
    await manager.goto(baseUrl + '/ayarlar/llm');
    await manager.getByLabel('İstek biçimi').selectOption('openai');
    await manager.getByLabel('Temel adres').fill(llmBaseUrl);
    await manager.getByLabel('Sohbet adresi (isteğe bağlı)').fill('');
    await manager.getByLabel('Model').fill(llmModel);
    await manager.getByRole('button', {name: 'Kaydet'}).click();
    await manager.getByText('LLM bağlantı ayarları kaydedildi.').waitFor();

    // Reviewer: the 120,001-character text cannot be sent; the API refuses it with 422 as well.
    await openScriptPage(reviewer);
    await reviewer.getByText("Metin kurum içi LLM'e gönderilir ve inceleme geçmişinde saklanır; kişisel veri ve parola içermemelidir.").waitFor();
    await reviewer.getByLabel('SQL').fill('x'.repeat(120_001));
    await reviewer.getByRole('alert').filter({hasText: 'SQL metni en çok 120.000 karakter olabilir.'}).waitFor();
    assert.equal(await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).isDisabled(), true);
    const tooLong = await apiStatus(reviewer, '/script-reviews', {method: 'POST', body: {sql: 'x'.repeat(120_001)}});
    assert.equal(tooLong.status, 422);
    assert.equal(tooLong.body.detail.code, 'sql_text_too_long');

    // Stop: the run ends as cancelled and shows no partial result.
    await reviewer.getByLabel('SQL').fill(SQL);
    await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
    let live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
    await live.getByText(/Kural \d+ \/ \d+/).waitFor();
    await live.getByRole('button', {name: 'Analizi durdur'}).click();
    const stoppedAt = Date.now();
    await live.getByText('İnceleme durduruldu.').first().waitFor();
    assert.equal(await live.getByRole('button', {name: 'Sonuçları göster'}).count(), 0);
    await live.getByRole('button', {name: 'Kapat'}).click();
    const stopped = (await apiStatus(reviewer, '/review-runs?scope=mine')).body.items[0];
    assert.equal(stopped.status, 'cancelled');
    // object-review Requirement 15: no LLM call starts later than 5 seconds after the stop. This
    // is a negative check over time, so it waits past the window instead of for a UI state.
    await reviewer.waitForTimeout(6_000);
    const calls = (await apiStatus(manager, '/llm-calls?limit=500')).body.items.filter(
      (call) => call.review_run_id === stopped.id,
    );
    assert.ok(calls.length > 0, 'the stopped run made at least one LLM call');
    assert.equal(calls.filter((call) => Date.parse(call.started_at) > stoppedAt + 5_000).length, 0);

    // Full run with a label: live progress, then line-referenced findings.
    await reviewer.getByLabel('Sonuçlarda görünecek ad (isteğe bağlı)').fill(LABEL);
    await reviewer.getByRole('button', {name: 'Kurallara göre incele'}).click();
    live = reviewer.getByRole('dialog', {name: 'Canlı inceleme'});
    await live.getByRole('progressbar', {name: 'İnceleme ilerlemesi'}).waitFor();
    await live.getByText(/belirteç/).first().waitFor();
    // A real model answers every rule in turn; allow minutes, not a stub's seconds.
    await live.getByText('İnceleme tamamlandı.').waitFor({timeout: 900_000});
    await live.getByRole('button', {name: 'Sonuçları göster'}).click();
    const results = reviewer.getByRole('dialog', {name: 'İnceleme sonuçları'});
    await results.getByText('Satır 4').first().waitFor();
    // Before marking: the fix comment's "Satır N" points at the NOLOCK line of the downloaded file.
    const [liveSql] = await Promise.all([
      reviewer.waitForEvent('download'),
      results.getByRole('button', {name: 'SQL indir'}).click(),
    ]);
    const liveSqlText = await readFile(await liveSql.path(), 'utf8');
    const lineRef = /- Kural01 — Sat[ıi]r (\d+) —/.exec(liveSqlText);
    assert.ok(lineRef, 'the SQL export lists the Kural01 finding');
    const fileLines = liveSqlText.split(/\r?\n/);
    assert.match(fileLines[Number(lineRef[1]) - 1], /NOLOCK/);

    const mark = results.getByRole('checkbox', {name: 'Kural01 bulgu 1 yanlış pozitif'});
    // The mark is saved on the server first; the box turns on when the answer arrives.
    await mark.click();
    await expect(mark).toBeChecked();
    await results.getByRole('button', {name: 'Kapat'}).click();

    // Another browser of the same reviewer sees the run with its mark, and downloads both files.
    const secondBrowser = await newPage();
    await signIn(secondBrowser, accounts.reviewer);
    await secondBrowser.getByRole('navigation', {name: message('shell.navigation')}).getByRole('link', {name: 'İnceleme geçmişi'}).click();
    const row = secondBrowser.getByRole('button', {name: new RegExp(`^${LABEL} — Tamamlandı`)});
    await row.click();
    const detail = secondBrowser.getByRole('region', {name: 'sql.' + LABEL});
    await detail.waitFor();
    assert.equal(await secondBrowser.getByRole('checkbox', {name: 'Kural01 bulgu 1 yanlış pozitif'}).isChecked(), true);

    const [csvDownload] = await Promise.all([
      secondBrowser.waitForEvent('download'),
      secondBrowser.getByRole('button', {name: 'CSV indir'}).click(),
    ]);
    assert.match(csvDownload.suggestedFilename(), /^sql-review-/);
    const csv = await readFile(await csvDownload.path(), 'utf8');
    assert.equal(csv.charCodeAt(0), 0xfeff, 'CSV starts with a UTF-8 BOM');
    assert.match(csv, /\r\n/);
    assert.match(csv.split('\r\n')[0], /^﻿generated_at,database,schema,name,object_type,rule_id,tier,status,severity,description,line_reference,code_snippet,false_positive,rule_group$/);
    // The false-positive column is followed by the rule_group column (review-history-export 1.4.0).
    assert.match(csv, /Kural01.*,true,[^\r\n]*\r\n/);

    const [sqlDownload] = await Promise.all([
      secondBrowser.waitForEvent('download'),
      secondBrowser.getByRole('button', {name: 'SQL indir'}).click(),
    ]);
    assert.match(sqlDownload.suggestedFilename(), /^sql-review-source-/);
    const sqlFile = await readFile(await sqlDownload.path(), 'utf8');
    assert.match(sqlFile, /SQL Review - Duzeltilmesi Gereken Yerler/);
    // The false-positive finding is left out of the fix-comment block (history Requirement 9).
    assert.doesNotMatch(sqlFile, /- Kural01 —/);
    assert.ok(sqlFile.includes(SQL.split('\n')[3]), 'the reviewed text is below the comment block');

    const runId = (await apiStatus(secondBrowser, '/review-runs?scope=mine')).body.items.find((item) => item.title === LABEL).id;

    // A second reviewer cannot see the run or its SQL export.
    const other = await newPage();
    await signIn(other, accounts.secondReviewer);
    assert.equal((await apiStatus(other, `/review-runs/${runId}`)).status, 404);
    assert.equal((await apiStatus(other, `/review-runs/${runId}/exports/sql`)).status, 404);

    // The rule manager sees it under all runs and downloads SQL, but cannot mark or delete it.
    await manager.goto(baseUrl + '/gecmis');
    await manager.getByLabel('Tüm incelemeler').check();
    await manager.getByRole('button', {name: new RegExp(`^${LABEL} — Tamamlandı`)}).click();
    await manager.getByText('Bu inceleme başka bir kullanıcıya ait; yalnız okunabilir.').waitFor();
    assert.equal(await manager.getByRole('checkbox', {name: /yanlış pozitif/}).count(), 0);
    assert.equal((await apiStatus(manager, `/review-runs/${runId}/exports/sql`)).status, 200);
    assert.equal((await apiStatus(manager, `/review-runs/${runId}`, {method: 'DELETE'})).status, 403);
    const findingId = (await apiStatus(manager, `/review-runs/${runId}`)).body.results[0].findings[0].id;
    const managerMark = await apiStatus(manager, `/review-runs/${runId}/findings/${findingId}/false-positive`, {
      method: 'PUT',
      body: {false_positive: false},
    });
    assert.equal(managerMark.status, 403);
    assert.equal(managerMark.body.detail.code, 'review_run_not_owner');

    // The owner deletes the run after confirming.
    await secondBrowser.getByRole('button', {name: `${LABEL} incelemesini sil`}).click();
    await secondBrowser.getByRole('dialog', {name: 'Bu inceleme silinsin mi?'}).getByRole('button', {name: 'Sil'}).click();
    await secondBrowser.getByText('İnceleme silindi.').waitFor();
    assert.equal((await apiStatus(secondBrowser, `/review-runs/${runId}`)).status, 404);
  } finally {
    // Remove the stopped run and any leftover run of this scenario, then restore the LLM settings.
    const runs = await apiStatus(reviewer, '/review-runs?scope=mine&page_size=200');
    for (const item of runs.body?.items ?? []) {
      if (item.title === LABEL || item.status === 'cancelled') await apiStatus(reviewer, `/review-runs/${item.id}`, {method: 'DELETE'});
    }
    if (llmBaseUrl && previous.editable) {
      const restored = await apiStatus(manager, '/llm-connection', {
        method: 'PUT',
        body: {
          chat_api: previous.chat_api,
          base_url: previous.base_url ?? '',
          chat_url: previous.chat_url ?? '',
          model: previous.model,
        },
      });
      assert.equal(restored.status, 200);
    }
  }
}, {
  // Without an LLM endpoint the script review is refused with 503 llm_not_configured by contract.
  expectedServerErrors: llmBaseUrl ? [] : [/^503 POST .*\/api\/dwhcodereview\/v1\/script-reviews$/],
});
