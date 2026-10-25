// Standalone candidate-only validation; no relay/Webull schemas are loaded.
import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
const database = new PGlite();
try {
  await database.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;');
  await database.exec(await readFile(new URL('../provider-connect/flow_store.sql', import.meta.url), 'utf8'));
  await database.exec(await readFile(new URL('provider_flows.sql', import.meta.url), 'utf8'));
  process.stdout.write('PASS provider_flows.sql (isolated PGlite candidate)\n');
} catch (error) {
  console.error('Provider SQL failed:', error.message, error.where ?? '', error.detail ?? '');
  process.exitCode = 1;
} finally {
  await database.close();
}
