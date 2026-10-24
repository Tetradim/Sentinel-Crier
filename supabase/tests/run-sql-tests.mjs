import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const folder=path.dirname(fileURLToPath(import.meta.url));
const database=new PGlite({extensions:{pgcrypto}});
try {
  await database.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA extensions;');
  const migrations=path.join(folder,'../migrations');
  for(const file of (await readdir(migrations)).filter(x=>x.endsWith('.sql')).sort()) {
    await database.exec(await readFile(path.join(migrations,file),'utf8'));
  }
  // Pending Webull state is tested explicitly; it is not a deployed migration.
  await database.exec(await readFile(path.join(folder,'../webull-connect/session_store.sql'),'utf8'));
  await database.exec(await readFile(path.join(folder,'../webull-connect/token_store.sql'),'utf8'));
  const tests=(await readdir(folder)).filter(x=>x.endsWith('.sql')).sort();
  if(!tests.length) throw Error('No SQL regression tests found');
  for(const file of tests) {
    await database.exec(await readFile(path.join(folder,file),'utf8'));
    process.stdout.write(`PASS ${file}\n`);
  }
  process.stdout.write('PostgreSQL-compatible SQL tests passed; hosted Supabase integration remains separate.\n');
} catch (error) {
  console.error('SQL validation failed:', error.message, error.code ?? '', error.detail ?? '', error.hint ?? '', 'position', error.position ?? '', error.where ?? '');
  process.exitCode=1;
} finally {
  await database.close();
}
