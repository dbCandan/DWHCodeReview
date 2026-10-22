import {message} from '../shared/harness.mjs';

/** The side menu: the daily work and, for the super admin, Yönetim. */
export function mainMenu(page) {
  return page.getByRole('navigation', {name: message('shell.navigation')});
}

/**
 * Open a section of the single Yönetim page (Kurallar, SQL bağlantısı, LLM çağrıları, Kullanıcılar,
 * ...): the side menu's "Yönetim", then the section's tab; the section title is a second-level
 * heading. Links are found by their labels as text, never by a regular expression built from the
 * argument.
 */
export async function openAdminSection(page, section, heading = section) {
  await mainMenu(page).getByRole('link', {name: 'Yönetim', exact: true}).click();
  const tabs = page.getByRole('navigation', {name: 'Yönetim bölümleri'});
  await tabs.getByRole('link', {name: section, exact: true}).click();
  await page.getByRole('heading', {name: heading, level: 2}).waitFor();
}

/** The side-menu label of each way to review. */
const REVIEW_LINKS = {Nesneler: 'Nesne incelemesi', 'SQL betiği': 'SQL betiği', Zamanlanmış: 'Zamanlanmış'};

/** Open one way to review: Nesneler, SQL betiği or Zamanlanmış. */
export async function openReview(page, mode, heading) {
  await mainMenu(page).getByRole('link', {name: REVIEW_LINKS[mode] ?? mode, exact: true}).click();
  if (heading) await page.getByRole('heading', {name: heading, level: 1}).waitFor();
}

/** Open the rule library; its page is "Yayımlanmış kurallar". */
export async function openLibrary(page, item = 'Yayımlanmış kurallar') {
  await mainMenu(page).getByRole('link', {name: 'Kural kitaplığı', exact: true}).click();
  await page.getByRole('heading', {name: item, level: 1}).waitFor();
}
