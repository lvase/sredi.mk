import { expect, test, type Page } from "@playwright/test";

const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64"
);

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill("testpass");
  await page.getByRole("button", { name: "Најави се" }).click();
  await expect(page).toHaveURL(/\/staff$/);
}

async function fillReport(page: Page, prefix: string) {
  await page.locator('input[name="location_text"]').fill(`${prefix} локација`);
  await page.locator('input[name="title"]').fill(`${prefix} наслов`);
  await page.locator('textarea[name="description"]').fill(`${prefix} опис на проблемот`);
  await page.locator('input[name="consent"]').check();
}

test("citizen can preview a photo, submit, and open tracking", async ({ page }) => {
  await page.goto("/konce/prijavi");
  await expect(page.getByText(/Намерно лажни, измамнички или манипулирани пријави/)).toBeVisible();
  await fillReport(page, "E2E јавна");
  await page.locator('input[name="photos"]').setInputFiles({
    name: "problem.png",
    mimeType: "image/png",
    buffer: ONE_PIXEL_PNG
  });
  await expect(page.getByAltText("problem.png")).toBeVisible();
  await page.getByRole("button", { name: "Испрати пријава" }).click();
  await expect(page.getByRole("heading", { name: "Пријавата е примена" })).toBeVisible();
  const code = await page.locator(".font-mono").innerText();
  expect(code.length).toBeGreaterThan(5);
  await page.getByRole("link", { name: "Провери статус" }).click();
  await expect(page).toHaveURL(new RegExp(`/konce/sledi\\?code=${code}`));
});

test("staff feedback and municipality isolation survive an account switch", async ({ page }) => {
  await login(page, "konce-staff");
  await expect(page.locator("h3:visible, strong:visible").filter({ hasText: "E2E Конче пријава" })).toBeVisible();
  await expect(page.getByText("E2E Радовиш пријава")).toHaveCount(0);
  expect((await page.request.get("/api/staff/attachments/1/")).status()).toBe(200);

  await page.goto("/staff/issues/1");
  await page.locator('select[name="priority"]').selectOption("high");
  await page.getByRole("button", { name: "Зачувај промени" }).click();
  await expect(page.getByText("Промените се зачувани.")).toBeVisible();

  await page.locator('textarea[name="body"]').fill("E2E јавно ажурирање");
  await page.locator('input[name="is_internal"]').uncheck();
  await page.getByRole("button", { name: "Додај коментар" }).click();
  await expect(page.getByText("Коментарот е додаден.")).toBeVisible();

  await page.locator('select[name="status"]').selectOption("resolved");
  await page.getByRole("button", { name: "Зачувај статус" }).click();
  await expect(page.getByText("За овој статус мора да внесете белешка.")).toBeVisible();

  await page.locator('select[name="status"]').selectOption("accepted");
  await page.getByRole("button", { name: "Зачувај статус" }).click();
  await expect(page.getByText("Статусот е зачуван.")).toBeVisible();

  await page.getByRole("button", { name: "Одјава" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/konce/sledi?code=E2EKONCE01");
  await expect(page.getByText("E2E јавно ажурирање")).toBeVisible();
  await expect(page.getByText("Статусот е променет во „Прифатена“.")).toBeVisible();
  await login(page, "radovis-staff");
  await expect(page.locator("h3:visible, strong:visible").filter({ hasText: "E2E Радовиш пријава" })).toBeVisible();
  await expect(page.getByText("E2E Конче пријава")).toHaveCount(0);
  expect((await page.request.get("/api/staff/attachments/1/")).status()).toBe(404);
  await page.goto("/staff/issues/1");
  await expect(page.getByText("Не може да се вчитаат податоците").or(page.getByText("Настана грешка."))).toBeVisible();
});

test("rate limited citizen sees an actionable cooldown", async ({ page }) => {
  await page.goto("/radovis/prijavi");
  const optionsResponse = await page.request.get("/api/municipalities/radovis/form-options/");
  const options = (await optionsResponse.json()).data;
  const csrfResponse = await page.request.get("/api/auth/csrf/");
  const csrfToken = (await csrfResponse.json()).data.csrfToken;

  for (let index = 0; index < 3; index += 1) {
    const response = await page.request.post("/api/municipalities/radovis/issues/", {
      headers: { "X-CSRFToken": csrfToken },
      data: {
        settlement: options.settlements[0].id,
        category: options.categories[0].id,
        title: `Rate seed ${index}`,
        description: `Rate description ${index}`,
        location_text: `Rate location ${index}`,
        consent: "on",
        website: ""
      }
    });
    expect(response.status()).toBe(201);
  }

  await fillReport(page, "E2E ограничена");
  await page.getByRole("button", { name: "Испрати пријава" }).click();
  await expect(page.getByText(/Нова пријава ќе може да се испрати за/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Почекај/ })).toBeDisabled();
});
