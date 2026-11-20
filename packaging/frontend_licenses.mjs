import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const [frontend, output] = process.argv.slice(2)
const lock = JSON.parse(await readFile(join(frontend, 'package-lock.json'), 'utf8'))
const notices = ['ArknightsUnpacker Vue workbench · third-party notices']

for (const [path, dependency] of Object.entries(lock.packages)) {
  if (!path || dependency.dev) continue
  const directory = join(frontend, path)
  const entries = await readdir(directory).catch(error => {
    if (dependency.optional && error.code === 'ENOENT') return []
    throw error
  })
  if (entries.length === 0) continue
  const manifest = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'))
  const files = entries.filter(file => /^(licen[cs]e|notice|copying)([.-]|$)/i.test(file))
  notices.push(`${manifest.name} ${manifest.version} (${manifest.license ?? 'see notice'})`)
  for (const file of files.sort()) notices.push((await readFile(join(directory, file), 'utf8')).trim())
}

await writeFile(output, notices.join('\n\n') + '\n', 'utf8')
