const fs = require('fs'); let s = fs.readFileSync('capture-perm.spec.ts', 'utf8')
const r = (a, b) => { if (!s.includes(a)) throw new Error('missing ' + a.slice(0, 40)); s = s.replace(a, b) }
r("  await expect(p.getByText('Provider saved.')).toBeVisible()\n", "  await expect(p.getByText('Provider saved.')).toBeVisible()\n  await expect(dlg(p)).toBeHidden()\n")
r("  await d.getByRole('button', { name: 'Save provider' }).click()\n  await expect(p.getByRole('cell', { name: /Ollama \(embeddings\)/ })).toBeVisible()", "  await d.getByRole('button', { name: 'Save provider' }).click()\n  await expect(dlg(p)).toBeHidden()\n  await expect(p.getByText('Ollama (embeddings)').first()).toBeVisible()")
fs.writeFileSync('capture-perm.spec.ts', s); console.log('ok')
