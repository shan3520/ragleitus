import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const LLM_URL = process.env.E2E_LLM_URL ?? "http://localhost:9999/v1";
const SAMPLES = path.resolve(__dirname, "../../samples");
const PASSWORD = "correct-horse-battery";

async function register(page: Page, username: string) {
  await page.goto("/register");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
}

test("a signed-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("from sign-up to a cited, evaluated answer", async ({ page }) => {
  const username = `e2e-${Date.now().toString(36)}`;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await test.step("register and see the getting-started checklist", async () => {
    await register(page, username);
    await expect(page.getByRole("heading", { name: `Welcome, ${username}` })).toBeVisible();
    await expect(page.getByText("Get started")).toBeVisible();
  });

  await test.step("add a provider key; only the masked key comes back", async () => {
    await page.goto("/providers");
    await page.getByLabel("Provider", { exact: true }).selectOption("custom");
    await page.getByLabel("API key").fill("stub-key");
    await page.getByLabel("Base URL").fill(LLM_URL);
    await page.getByRole("button", { name: "Save key" }).click();
    await expect(page.getByText(/Saved .* key/)).toBeVisible();
    await expect(page.getByRole("cell", { name: LLM_URL })).toBeVisible();
    await expect(page.getByText("stub-key", { exact: true })).toHaveCount(0);
  });

  await test.step("upload two documents and wait until they are indexed", async () => {
    await page.goto("/documents");
    await page.getByTestId("file-input").setInputFiles([
      path.join(SAMPLES, "roboarm-x2-faq.pdf"),
      path.join(SAMPLES, "employee-handbook.md"),
    ]);
    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: "Ready" })).toHaveCount(2, { timeout: 30_000 });
  });

  await test.step("ask a question and get a streamed answer with a citation", async () => {
    await page.goto("/chat");
    await page.getByLabel("Model", { exact: true }).fill("stub-model");
    await page.getByLabel("Message").fill("What does error code E-4711 mean?");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Evaluate answer" })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".prose-answer")).toContainText("E-4711");
    await expect(page).toHaveURL(/\/chat\?c=\d+/);
  });

  await test.step("evaluate the answer", async () => {
    await page.getByRole("button", { name: "Evaluate answer" }).click();
    await expect(page.getByText("Faithfulness")).toBeVisible({ timeout: 30_000 });
  });

  await test.step("a citation opens the cited passage", async () => {
    await page.locator(".prose-answer a").first().click();
    await expect(page).toHaveURL(/\/documents\/\d+#chunk-\d+$/);
    await expect(page.locator('[aria-current="location"]')).toContainText("E-4711");
  });

  await test.step("telemetry and evaluations show the calls", async () => {
    await page.goto("/telemetry");
    await expect(page.getByRole("heading", { name: "Requests per day" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "stub-model" }).first()).toBeVisible();

    await page.goto("/evaluations");
    const openChat = page.getByRole("link", { name: "Open chat" }).first();
    await expect(openChat).toHaveAttribute("href", /\/chat\?c=\d+/);
  });

  await test.step("change the password and sign in with the new one", async () => {
    const next = "a-brand-new-password";
    await page.goto("/settings");
    await page.getByLabel("Current password").fill(PASSWORD);
    await page.getByLabel("New password", { exact: true }).fill(next);
    await page.getByLabel(/Confirm/).fill(next);
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByText("Password changed.")).toBeVisible();

    await page.getByRole("main").getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(next);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL("/");
    await expect(page.getByText("Get started")).toHaveCount(0);
  });

  expect(errors).toEqual([]);
});
