const fs = require('fs'); let s = fs.readFileSync('capture-perm.spec.ts', 'utf8')
const a = "  await expect(p.getByText('Model added as proposed.')).toBeVisible()\n"
if (!s.includes(a)) throw new Error('a')
s = s.replace(a, a + "  await expect(dlg(p)).toBeHidden()\n")
const b = "  await d.getByRole('button', { name: 'Add model' }).click()\n  await expect(p.getByRole('cell', { name: /nomic-embed-text/ })).toBeVisible()"
if (!s.includes(b)) throw new Error('b')
s = s.replace(b, "  await d.getByRole('button', { name: 'Add model' }).click()\n  await expect(dlg(p)).toBeHidden()\n  await expect(p.getByText('nomic-embed-text').first()).toBeVisible()")
fs.writeFileSync('capture-perm.spec.ts', s); console.log('ok')
