import type {DbObject} from '@/types';

type Keyed = Pick<DbObject, 'database' | 'schema' | 'name'>;

/** Identity of an object in the pool: db.schema.name (SQL Server identifiers are case-insensitive). */
export function objectKey(object: Keyed): string {
  return `${object.database}.${object.schema}.${object.name}`.toLowerCase();
}

export function objectLabel(object: Keyed): string {
  return `${object.database}.${object.schema}.${object.name}`;
}

/** Appends `incoming` to `pool`, skipping duplicates (both against the pool and within `incoming`). */
export function mergePool<T extends Keyed>(pool: T[], incoming: T[]): {pool: T[]; added: number; skipped: number} {
  const seen = new Set(pool.map(objectKey));
  const next = [...pool];
  let added = 0;
  for (const object of incoming) {
    const key = objectKey(object);
    if (seen.has(key)) continue;
    seen.add(key);
    next.push(object);
    added += 1;
  }
  return {pool: next, added, skipped: incoming.length - added};
}

export function removeFromPool<T extends Keyed>(pool: T[], keys: Iterable<string>): T[] {
  const drop = new Set(keys);
  return pool.filter((object) => !drop.has(objectKey(object)));
}

export type SortKey = 'database' | 'schema' | 'name' | 'type' | 'create_date' | 'modify_date';
export type SortDir = 'asc' | 'desc';

export function sortObjects<T extends DbObject>(items: T[], key: SortKey, dir: SortDir): T[] {
  const factor = dir === 'asc' ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key] ?? '';
    const bv = b[key] ?? '';
    const primary = key.endsWith('_date')
      ? new Date(av).getTime() - new Date(bv).getTime()
      : String(av).localeCompare(String(bv), 'tr-TR', {sensitivity: 'base'});
    if (primary !== 0) return primary * factor;
    return objectKey(a).localeCompare(objectKey(b));
  });
}
