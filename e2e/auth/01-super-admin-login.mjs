import {
  withBrowser,
  baseUrl,
  apiPrefix,
  accounts,
  message,
  signIn,
} from "../shared/harness.mjs";

await withBrowser(
  "super-admin login, memory-only token, silent refresh and sign-out",
  async ({ page, assert }) => {
    await page.goto(baseUrl + "/");
    await page.waitForURL(baseUrl + "/login");

    await signIn(page, accounts.superAdmin);
    await page.waitForURL(baseUrl + "/");
    await page.getByRole("heading", { name: "ReviewX" }).waitFor();

    // directory-login Requirement 6-7: no token or session copy in browser storage, and the
    // refresh cookie is HttpOnly (invisible to page scripts).
    const storage = await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
      cookie: document.cookie,
    }));
    assert.deepEqual(storage, { local: 0, session: 0, cookie: "" });
    const cookies = await page.context().cookies();
    const refresh = cookies.find((cookie) => cookie.name === "dwhcodereview_refresh");
    assert.ok(refresh, "refresh cookie is set");
    assert.equal(refresh.httpOnly, true);
    assert.equal(refresh.sameSite, "Strict");
    assert.equal(refresh.path, apiPrefix + "/auth");

    // The tenant header is still enforced for a bearer request.
    const tenantCheck = await page.evaluate(async (prefix) => {
      const refreshed = await fetch(prefix + "/auth/refresh", { method: "POST" });
      const session = await refreshed.json();
      const missing = await fetch(prefix + "/auth/me", {
        headers: { Authorization: "Bearer " + session.access_token },
      });
      const me = await fetch(prefix + "/auth/me", {
        headers: {
          Authorization: "Bearer " + session.access_token,
          "x-tenant-id": session.user.tenant_id,
        },
      });
      return { missing: missing.status, me: me.status, body: await me.json() };
    }, apiPrefix);
    assert.equal(tenantCheck.missing, 400);
    assert.equal(tenantCheck.me, 200);
    assert.equal(tenantCheck.body.is_super_admin, true);
    assert.ok(tenantCheck.body.roles.includes("super_admin"));

    // A refresh request from another origin is refused (CSRF guard on the cookie endpoints).
    const foreign = await page.request.post(baseUrl + apiPrefix + "/auth/refresh", {
      headers: { Origin: "https://attacker.invalid" },
    });
    assert.equal(foreign.status(), 403);

    // Reload drops the in-memory token; the session comes back through the refresh cookie.
    await page.reload();
    await page.getByRole("heading", { name: "ReviewX" }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/");

    await page.getByRole("button", { name: message("auth.session.signOut") }).click();
    await page.waitForURL(baseUrl + "/login");
    const afterLogout = await page.evaluate(async (prefix) => {
      const response = await fetch(prefix + "/auth/refresh", { method: "POST" });
      return response.status;
    }, apiPrefix);
    assert.equal(afterLogout, 401);
    await page.goto(baseUrl + "/");
    await page.waitForURL(baseUrl + "/login");
  },
);
