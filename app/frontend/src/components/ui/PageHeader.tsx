import {createContext, useContext, useEffect, type ReactNode} from 'react';
import {config} from '@/lib/config';

/** Set by a host page (Yönetim) that shows another page as one of its sections. */
const EmbeddingContext = createContext<string | null>(null);

/** Render a page as a section of `host`: its title becomes a second-level heading. */
export function EmbeddedPage({host, children}: {host: string; children: ReactNode}) {
  return <EmbeddingContext.Provider value={host}>{children}</EmbeddingContext.Provider>;
}

/** Page title, the document title and the page's main actions. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const host = useContext(EmbeddingContext);
  useEffect(() => {
    document.title = host ? `${title} · ${host} · ${config.productName}` : `${title} · ${config.productName}`;
  }, [title, host]);
  const Heading = host ? 'h2' : 'h1';
  return (
    <header className={host ? 'page-header page-header-embedded' : 'page-header'}>
      <div className="page-header-text">
        <Heading>{title}</Heading>
        {description !== undefined && <p className="page-description">{description}</p>}
      </div>
      {actions !== undefined && <div className="page-actions">{actions}</div>}
    </header>
  );
}
