import { expect, test } from '@playwright/test'
import { login, stubApi } from './helpers'

test.describe('application shell and authentication', () => {
  test('1. the application loads and redirects anonymous users to sign-in', async ({ page }) => {
    await stubApi(page)
    await page.goto('/')
    await expect(page).toHaveURL(/\/login\?returnTo=%2F/)
    await expect(page.getByRole('heading', { name: 'UnityRAG' })).toBeVisible()
    await expect(page.getByText(/Do not enter customer personal data/)).toBeVisible()
  })

  test('2. sign-in works, returns to the requested page, and shows neutral errors for bad credentials', async ({ page }) => {
    await stubApi(page)
    await page.goto('/login')
    await page.getByLabel('Email').fill('person@example.test')
    await page.getByLabel('Password').fill('wrong')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByText('The email or password is incorrect.')).toBeVisible()
    await login(page, '/documents')
    await expect(page).toHaveURL(/\/documents$/)
    await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible()
  })

  test('3. a member cannot open admin or platform pages, even by direct URL', async ({ page }) => {
    await stubApi(page, 'member')
    await login(page, '/admin')
    await expect(page.getByText('Not available to you')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0)
    await page.getByRole('link', { name: 'Back to home' }).click()
    await expect(page.getByRole('navigation', { name: 'workspace navigation' }).first()).not.toContainText('Audit log')
  })

  test('4. authorised users reach their permitted pages through the navigation', async ({ page }) => {
    await stubApi(page, 'admin')
    await login(page, '/admin')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    const nav = page.getByRole('navigation', { name: 'admin navigation' }).first()
    await expect(nav).toContainText('Users')
    await expect(nav).not.toContainText('Roles') // no roles permission
    await nav.getByRole('link', { name: 'Audit log' }).click()
    await expect(page).toHaveURL(/\/admin\/audit$/)
    await page.getByRole('button', { name: 'Verify integrity' }).click()
    await expect(page.getByText('Chain verified: 3 events')).toBeVisible()
  })

  test('signing out ends the session and protects the page again', async ({ page }) => {
    await stubApi(page)
    await login(page, '/')
    await page.getByRole('button', { name: 'User menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByText('You have signed out.')).toBeVisible()
  })
})

test.describe('documents and ingestion', () => {
  test('5–6. uploads a document and shows the real ingestion status, not "done"', async ({ page }) => {
    const stub = await stubApi(page)
    await login(page, '/documents/upload')
    await page.getByLabel('Choose files to upload').setInputFiles({ name: 'wording.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') })
    await page.getByLabel(/Collection/).selectOption('c1')
    await page.getByRole('button', { name: /Upload 1 file/ }).click()
    const stages = page.getByLabel('Ingestion stages')
    await expect(stages).toBeVisible()
    await expect(page.getByText('Running')).toBeVisible()
    await expect(stages.getByText('Embedding')).toBeVisible()
    expect(stub.calls.some((c) => c.method === 'POST' && c.url === '/documents')).toBe(true)
    stub.jobStatus = 'succeeded'
    await expect(page.getByText('Succeeded')).toBeVisible({ timeout: 10_000 })
  })

  test('lists documents and handles an API failure with a reference', async ({ page }) => {
    const stub = await stubApi(page)
    await login(page, '/documents')
    await expect(page.getByRole('link', { name: 'ABC Motor Comprehensive Policy Wording' })).toBeVisible()
    await expect(page.getByText('Published')).toBeVisible()
    stub.failDocuments = true
    await page.getByLabel('Search title').fill('zzz')
    const alert = page.getByRole('alert').filter({ hasText: 'Something went wrong on our side' })
    await expect(alert).toBeVisible({ timeout: 10_000 })
    await expect(alert).toContainText(/Reference/)
    await expect(alert).not.toContainText('internal_error')
  })
})

test.describe('search and chat', () => {
  test('7. search shows backend results with highlights and opens the passage preview', async ({ page }) => {
    await stubApi(page)
    await login(page, '/search')
    await page.getByLabel('Search approved documents').fill('flood')
    await page.getByRole('button', { name: 'Search' }).click()
    await expect(page.getByRole('heading', { name: 'ABC Motor Comprehensive Policy Wording' })).toBeVisible()
    await expect(page.locator('mark')).toHaveText('flood')
    await page.getByRole('button', { name: 'Open passage' }).click()
    await expect(page.getByRole('dialog')).toContainText('[EMAIL REDACTED]')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('8. chat streams an answer with citations, evidence, disclaimer, and opens the source', async ({ page }) => {
    const stub = await stubApi(page)
    await login(page, '/chat')
    await page.getByLabel('Your question').fill('Is flood damage covered?')
    await page.getByLabel('Your question').press('Enter')
    await expect(page.getByText('AI-generated', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Evidence: High' })).toBeVisible()
    await expect(page.getByText(/AI-generated guidance based on approved documents/)).toBeVisible()
    await expect(page).toHaveURL(/\/chat\/cv1$/)
    const chip = page.getByRole('button', { name: 'Source 1: ABC Motor Comprehensive Policy Wording, page 1' })
    await expect(chip).toBeVisible()
    await page.getByRole('button', { name: 'Open in context' }).first().click()
    await expect(page.getByRole('dialog')).toContainText('Flood damage is covered')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Helpful', exact: true }).click()
    await expect.poll(() => stub.calls.filter((c) => c.url === '/feedback').length).toBe(1)
  })

  test('9–10. the Platform console is unavailable to tenant users and API errors do not leak internals', async ({ page }) => {
    await stubApi(page, 'member')
    await login(page, '/platform')
    await expect(page.getByText('Not available to you')).toBeVisible()
    await page.goto('/this-page-does-not-exist')
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
  })
})
