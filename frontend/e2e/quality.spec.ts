import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const routes = [
  ["home", "/"],
  ["municipality", "/konce"],
  ["report", "/konce/prijavi"],
  ["tracking", "/konce/sledi?code=E2EVISUAL01"],
  ["statistics", "/konce/statistika"]
] as const;

async function login(page: Page) {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill("konce-staff");
  await page.locator('input[name="password"]').fill("testpass");
  await page.getByRole("button", { name: "Најави се" }).click();
  await expect(page).toHaveURL(/\/staff$/);
}

test("critical public and staff routes have no serious axe violations", async ({ page }) => {
  for (const [, route] of routes) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations.filter((item) => ["serious", "critical"].includes(item.impact || ""))).toEqual([]);
  }
  await login(page);
  for (const route of ["/staff", "/staff/issues/1", "/staff/security"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations.filter((item) => ["serious", "critical"].includes(item.impact || ""))).toEqual([]);
  }
});

test("public statistics expose only moderated titles", async ({ page }) => {
  await page.goto("/konce/statistika?period=all");
  await expect(page.getByText("Јавен: визуелна пријава")).toBeVisible();
  await expect(page.getByText("E2E визуелна пријава")).toHaveCount(0);
  await expect(page.getByText("Детерминистички опис за визуелна регресија")).toHaveCount(0);
  await expect(page.getByText("Детерминистичка локација")).toHaveCount(0);
});

for (const width of [320, 768, 1440]) {
  test(`responsive visual baselines at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 320 ? 720 : 900 });
    for (const [name, route] of routes) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await page.mouse.move(0, 0);
      await expect(page).toHaveScreenshot(`${name}-${width}.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixels: 100,
        threshold: 0.25,
        mask: [page.locator("time"), page.locator(".metric-card strong"), page.locator("[data-visual-mask]")]
      });
    }
    await login(page);
    for (const [name, route] of [["staff-dashboard", "/staff?search=E2EVISUAL01"], ["staff-issue-detail", "/staff/issues/3"]] as const) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await page.mouse.move(0, 0);
      await expect(page).toHaveScreenshot(`${name}-${width}.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixels: name === "staff-dashboard" && width === 1440 ? 2000 : 100,
        threshold: 0.25,
        mask: [page.locator("time"), page.locator(".metric-card strong"), page.locator("[data-visual-mask]")]
      });
    }
  });
}

test("key screens reflow at 200 percent text size on a narrow viewport", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 320, height: 720 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const failures: string[] = [];
  async function checkReflow(route: string) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await page.evaluate(async () => {
      document.documentElement.style.fontSize = "200%";
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    });
    const overflow = await page.evaluate(() => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      elements: [...document.querySelectorAll("main *, header *")]
        .filter((element) => element.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 6).map((element) => `${element.tagName}.${element.className}`)
    }));
    if (overflow.scrollWidth > overflow.width + 1) failures.push(`${route}: ${overflow.scrollWidth}px; ${overflow.elements.join(", ")}`);
  }
  for (const [, route] of routes) await checkReflow(route);
  await login(page);
  await checkReflow("/staff");
  await checkReflow("/staff/issues/3");
  expect(failures).toEqual([]);
});

test("mobile navigation supports keyboard dismissal and restores focus", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/konce");
  const trigger = page.getByRole("button", { name: "Отвори мени" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await page.getByRole("dialog").getByRole("link", { name: "Следи пријава" }).click();
  await expect(page).toHaveURL(/\/konce\/sledi$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.goto("/");
  await page.getByRole("button", { name: "Отвори мени" }).click();
  await page.getByRole("dialog").getByRole("link", { name: "Избери општина" }).click();
  await expect(page).toHaveURL(/\/#municipalities$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Избери општина." })).toBeInViewport();
});
