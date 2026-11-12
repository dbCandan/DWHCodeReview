import {useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {useLocation, useNavigate} from 'react-router';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarClock,
  Check,
  Database,
  FileBarChart,
  FlaskConical,
  Funnel,
  ListChecks,
  Map as MapIcon,
  Play,
  ScanSearch,
  Sparkles,
  X,
} from 'lucide-react';
import {cn} from '@/lib/utils';
import {markTourSeen, onOpenTour, SPOTLIGHT_STEPS, tourSeen, type SpotlightStep, type TourStart} from '@/lib/tour';
import {useAnalyses, useConnections, useLlmSettings, useRules} from '@/hooks/queries';
import {useOverlay} from '@/components/ui/Overlay';
import {Button} from '@/components/ui/Button';
import {Kbd} from '@/components/ui/Badge';
import {TourDemo} from './TourDemo';

type Phase = 'welcome' | 'demo' | 'spotlight' | 'finish';

/**
 * First-run guide. Shown once per browser (and again from the header's help button): a welcome
 * card, a live demo that runs the real rule set over a sample procedure without any connection,
 * a spotlight walk over the real screens, and a "where to start" checklist with live status.
 */
export function WelcomeTour() {
  const [phase, setPhase] = useState<Phase | null>(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!tourSeen()) setPhase('welcome');
    return onOpenTour((start: TourStart) => {
      setStep(0);
      setPhase(start);
    });
  }, []);

  useEffect(() => {
    if (phase) markTourSeen();
  }, [phase]);

  const close = useCallback(() => setPhase(null), []);
  if (!phase) return null;

  if (phase === 'spotlight')
    return (
      <Spotlight
        index={step}
        onIndex={setStep}
        onBack={() => setPhase('demo')}
        onFinish={() => setPhase('finish')}
        onClose={close}
      />
    );

  return (
    <Modal onClose={close} wide={phase === 'demo'} label={phase === 'demo' ? 'Demo' : phase === 'finish' ? 'Nereden başlamalı' : 'Hoş geldiniz'}>
      {phase === 'welcome' && (
        <WelcomeCard
          onDemo={() => setPhase('demo')}
          onTour={() => {
            setStep(0);
            setPhase('spotlight');
          }}
          onSkip={close}
        />
      )}
      {phase === 'demo' && (
        <TourDemo
          onBack={() => setPhase('welcome')}
          onNext={() => {
            setStep(0);
            setPhase('spotlight');
          }}
        />
      )}
      {phase === 'finish' && <FinishCard onClose={close} onReplay={() => setPhase('welcome')} />}
    </Modal>
  );
}

/* ------------------------------------------------------------------ modal shell */

function Modal({children, onClose, wide, label}: {children: ReactNode; onClose: () => void; wide?: boolean; label: string}) {
  const panel = useRef<HTMLDivElement>(null);
  useOverlay(true, onClose, panel);
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto p-3 sm:items-center sm:p-6">
      <div className="fixed inset-0 animate-fade-in bg-black/60 backdrop-blur-[3px]" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className={cn(
          'relative flex w-full animate-pop-in flex-col overflow-hidden rounded-2xl border border-line-strong bg-elevated shadow-pop outline-none',
          wide ? 'max-w-6xl' : 'max-w-3xl',
        )}
      >
        <div className="absolute top-3 right-3 z-10">
          <Button variant="ghost" size="sm" iconOnly aria-label="Tanıtımı kapat" onClick={onClose}>
            <X className="size-4" />
          </Button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ welcome */

const FEATURES: {icon: ReactNode; title: string; body: string}[] = [
  {icon: <ListChecks />, title: 'Ekip standartlarınız', body: 'DWH kodlama ve performans kuralları: regex, yerleşik kontrol ve LLM.'},
  {icon: <Funnel />, title: 'Nesne havuzu', body: 'Veritabanı, şema, tür, tarih ve ada göre VE filtreleriyle seçim.'},
  {icon: <ScanSearch />, title: 'Adım adım analiz', body: 'Her nesne × kural kontrolü canlı ilerler; bulgular kodda işaretlenir.'},
  {icon: <FileBarChart />, title: 'Rapor ve istisnalar', body: 'HTML rapor, CSV; yanlış alarmları istisnayla susturun.'},
  {icon: <CalendarClock />, title: 'Zamanlanmış tarama', body: 'Yalnızca değişen nesneler; yeni ve çözülen bulgular karşılaştırılır.'},
  {icon: <Sparkles />, title: 'LLM kural asistanı', body: 'Kuralı anlatın; asistan yazar, doğrular, gürültüyü ölçer.'},
];

const FLOW = ['Bağlantı', 'Nesne havuzu', 'Kurallar', 'Bulgular & rapor'];

function WelcomeCard({onDemo, onTour, onSkip}: {onDemo: () => void; onTour: () => void; onSkip: () => void}) {
  const rules = useRules();
  const ruleCount = (rules.data ?? []).filter((r) => r.enabled).length;
  return (
    <div className="flex flex-col">
      <div className="relative overflow-hidden border-b border-line px-6 pt-7 pb-6 sm:px-8">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_70%_120%_at_0%_0%,color-mix(in_srgb,var(--color-accent)_16%,transparent),transparent_65%)]" />
        <div className="relative flex items-start gap-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-accent-solid text-accent-fg shadow-[0_6px_20px_-6px_var(--color-accent-solid)]">
            <ScanSearch className="size-[22px]" />
          </div>
          <div className="min-w-0 pr-8">
            <div className="text-[11.5px] font-semibold tracking-[0.08em] text-accent uppercase">Hoş geldiniz</div>
            <h2 className="mt-1 text-[22px] leading-7 font-semibold tracking-[-0.02em] text-fg">DWH Code Review</h2>
            <p className="mt-1.5 max-w-xl text-[13.5px] leading-[21px] text-fg-muted">
              SQL Server’daki prosedür, view ve fonksiyonlarınızı veri ambarı ekibinin standartlarına göre otomatik denetler; ihlalleri satır
              satır gösterir, raporlar ve zaman içinde izler.
            </p>
          </div>
        </div>
        <ol className="relative mt-5 flex flex-wrap items-center gap-1.5 text-[12px]">
          {FLOW.map((f, i) => (
            <li key={f} className="flex items-center gap-1.5">
              <span className="flex items-center gap-1.5 rounded-full border border-line-strong bg-surface/70 py-1 pr-2.5 pl-1 text-fg">
                <span className="flex size-5 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent tnum">{i + 1}</span>
                {f}
              </span>
              {i < FLOW.length - 1 && <ArrowRight className="size-3.5 text-fg-subtle" />}
            </li>
          ))}
        </ol>
      </div>

      <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <div key={f.title} className="flex gap-3 bg-elevated px-5 py-4">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-2 text-accent [&_svg]:size-4">{f.icon}</span>
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-fg">{f.title}</div>
              <p className="mt-0.5 text-[12px] leading-[18px] text-fg-muted">{f.body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3 border-t border-line bg-surface-2/40 px-6 py-4 sm:flex-row sm:items-center sm:px-8">
        <p className="text-[12.5px] text-fg-muted">
          {ruleCount > 0 ? (
            <>
              <b className="text-fg tnum">{ruleCount}</b> kural hazır. Önce bir dakikalık demoyu deneyin, sonra ekranları birlikte gezelim.
            </>
          ) : (
            'Önce bir dakikalık demoyu deneyin, sonra ekranları birlikte gezelim.'
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto sm:shrink-0">
          <Button variant="ghost" onClick={onSkip}>
            Şimdilik atla
          </Button>
          <Button variant="secondary" icon={<MapIcon className="size-4" />} onClick={onTour}>
            Ekranları gez
          </Button>
          <Button variant="primary" icon={<FlaskConical className="size-4" />} onClick={onDemo} data-autofocus>
            Demoyu başlat
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ spotlight */

const BUBBLE_W = 360;
const GAP = 14;
const EDGE = 12;
const PAD = 6;
/** How long a step waits for its element before showing the bubble in the middle. */
const FIND_TIMEOUT = 1400;

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

function placeBubble(target: Box | null, bubbleH: number, side: SpotlightStep['side']): {style: CSSProperties; sheet: boolean} {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (vw < 640) return {style: {}, sheet: true};
  const centre = {top: Math.max(EDGE, (vh - bubbleH) / 2), left: (vw - BUBBLE_W) / 2};
  if (!target) return {style: centre, sheet: false};
  const clampL = (l: number) => Math.min(Math.max(l, EDGE), vw - BUBBLE_W - EDGE);
  const clampT = (t: number) => Math.min(Math.max(t, EDGE), vh - bubbleH - EDGE);
  const fits = {
    right: target.left + target.width + GAP + BUBBLE_W <= vw - EDGE,
    left: target.left - GAP - BUBBLE_W >= EDGE,
    bottom: target.top + target.height + GAP + bubbleH <= vh - EDGE,
    top: target.top - GAP - bubbleH >= EDGE,
  };
  const at = {
    right: {top: clampT(target.top), left: target.left + target.width + GAP},
    left: {top: clampT(target.top), left: target.left - GAP - BUBBLE_W},
    bottom: {top: target.top + target.height + GAP, left: clampL(target.left)},
    top: {top: target.top - GAP - bubbleH, left: clampL(target.left)},
  };
  const order = [side ?? 'bottom', 'bottom', 'right', 'top', 'left'] as const;
  for (const s of order) if (fits[s]) return {style: at[s], sheet: false};
  // Large targets: float inside them, bottom-right.
  return {style: {top: vh - bubbleH - EDGE * 2, left: vw - BUBBLE_W - EDGE * 2}, sheet: false};
}

function Spotlight({
  index,
  onIndex,
  onBack,
  onFinish,
  onClose,
}: {
  index: number;
  onIndex: (i: number) => void;
  onBack: () => void;
  onFinish: () => void;
  onClose: () => void;
}) {
  const step = SPOTLIGHT_STEPS[index];
  const navigate = useNavigate();
  const {pathname} = useLocation();
  const panel = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [ready, setReady] = useState(false);
  const [bubbleH, setBubbleH] = useState(260);
  useOverlay(true, onClose, panel);

  const next = useCallback(() => (index + 1 < SPOTLIGHT_STEPS.length ? onIndex(index + 1) : onFinish()), [index, onIndex, onFinish]);
  const prev = useCallback(() => (index > 0 ? onIndex(index - 1) : onBack()), [index, onIndex, onBack]);

  // Open the step's page.
  useEffect(() => {
    if (pathname !== step.route) navigate(step.route);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step.route]);

  // Find the element (pages load asynchronously), bring it into view, then follow it every frame.
  useEffect(() => {
    setReady(false);
    setBox(null);
    const started = performance.now();
    let scrolled = false;
    let frame = 0;
    const tick = () => {
      const el = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
      const r = el?.getBoundingClientRect();
      if (el && r && r.width > 0 && r.height > 0) {
        if (!scrolled) {
          scrolled = true;
          el.scrollIntoView({block: r.height > window.innerHeight * 0.5 ? 'start' : 'center', behavior: 'smooth'});
        }
        const vh = window.innerHeight;
        const top = Math.max(r.top - PAD, 4);
        const bottom = Math.min(r.bottom + PAD, vh - 4);
        const next: Box = {top, left: r.left - PAD, width: r.width + PAD * 2, height: Math.max(bottom - top, 0)};
        setBox((b) => (b && b.top === next.top && b.left === next.left && b.width === next.width && b.height === next.height ? b : next));
        setReady(true);
      } else if (!step.target || performance.now() - started > FIND_TIMEOUT) {
        setBox(null);
        setReady(true);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [step]);

  useLayoutEffect(() => {
    if (panel.current) setBubbleH(panel.current.offsetHeight);
  }, [index, ready, box]);

  useEffect(() => {
    panel.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus({preventScroll: true});
  }, [index, ready]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        next();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, prev]);

  const place = placeBubble(box, bubbleH, step.side);
  const last = index === SPOTLIGHT_STEPS.length - 1;

  return createPortal(
    <div className="fixed inset-0 z-[60]" role="presentation">
      {/* Blocks the page underneath; the lit element is a window in this layer. */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} />
      {box ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-xl ring-2 ring-accent transition-[top,left,width,height] duration-300 ease-out"
          style={{...box, boxShadow: '0 0 0 9999px rgb(5 7 12 / 0.62), 0 0 0 6px color-mix(in srgb, var(--color-accent) 22%, transparent)'}}
        />
      ) : (
        <div aria-hidden className="pointer-events-none absolute inset-0 animate-fade-in bg-[rgb(5_7_12/0.62)]" />
      )}

      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-step-title"
        tabIndex={-1}
        className={cn(
          'absolute flex flex-col rounded-xl border border-line-strong bg-elevated shadow-pop outline-none transition-[top,left,opacity] duration-300 ease-out',
          place.sheet ? 'inset-x-2 bottom-2' : 'w-[360px]',
          ready ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        style={place.sheet ? undefined : place.style}
      >
        <div className="flex items-center gap-2 px-4 pt-3.5">
          <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent tnum">
            {index + 1} / {SPOTLIGHT_STEPS.length}
          </span>
          <div className="flex flex-1 items-center gap-1" aria-hidden>
            {SPOTLIGHT_STEPS.map((s, i) => (
              <span key={s.key} className={cn('h-1 flex-1 rounded-full', i <= index ? 'bg-accent' : 'bg-surface-3')} />
            ))}
          </div>
          <Button variant="ghost" size="xs" iconOnly aria-label="Turu kapat" onClick={onClose}>
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="px-4 pt-2.5 pb-3">
          <h3 id="tour-step-title" className="text-[14.5px] font-semibold tracking-[-0.01em] text-fg">
            {step.title}
          </h3>
          <p className="mt-1.5 text-[12.5px] leading-[19px] text-fg-muted">{step.body}</p>
          {step.points && (
            <ul className="mt-2.5 flex flex-col gap-1.5">
              {step.points.map((p) => (
                <li key={p} className="flex gap-2 text-[12.5px] leading-[18px] text-fg">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-ok" strokeWidth={2.5} />
                  {p}
                </li>
              ))}
            </ul>
          )}
          {step.key === 'palette' && (
            <div className="mt-2.5 flex items-center gap-1.5 text-[12px] text-fg-muted">
              <Kbd>Ctrl</Kbd>
              <Kbd>K</Kbd>
              <span>komut paleti</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-line px-3 py-2.5">
          <Button variant="ghost" size="sm" icon={<ArrowLeft className="size-3.5" />} onClick={prev}>
            Geri
          </Button>
          <span className="hidden text-[11px] text-fg-subtle sm:inline">← → ile gezinebilirsiniz</span>
          <Button variant="primary" size="sm" className="ml-auto" onClick={next} data-autofocus>
            {last ? 'Bitir' : 'İleri'}
            {!last && <ArrowRight className="size-3.5" />}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ finish */

function FinishCard({onClose, onReplay}: {onClose: () => void; onReplay: () => void}) {
  const navigate = useNavigate();
  const connections = useConnections();
  const llm = useLlmSettings();
  const analyses = useAnalyses();
  const go = (to: string) => {
    onClose();
    navigate(to);
  };
  const items: {icon: ReactNode; title: string; body: string; done: boolean; optional?: boolean; to: string; cta: string}[] = [
    {
      icon: <Database />,
      title: 'SQL Server bağlantısı ekleyin',
      body: 'Sunucu, alias veya host,port; “Test et” ile doğrulayın.',
      done: (connections.data ?? []).length > 0,
      to: '/connections',
      cta: 'Bağlantılar',
    },
    {
      icon: <Bot />,
      title: 'LLM modelini tanımlayın',
      body: 'Anlamsal kurallar ve kural asistanı için. Regex ve yerleşik kurallar LLM’siz çalışır.',
      done: !!llm.data?.enabled,
      optional: true,
      to: '/settings',
      cta: 'Ayarlar',
    },
    {
      icon: <Play />,
      title: 'İlk analizinizi başlatın',
      body: 'Havuzu filtreleyin, kural grubunu seçin, başlatın.',
      done: (analyses.data ?? []).length > 0,
      to: '/analyses/new',
      cta: 'Yeni Analiz',
    },
  ];
  const doneCount = items.filter((i) => i.done).length;
  return (
    <div className="flex flex-col">
      <div className="border-b border-line px-6 pt-6 pb-5 sm:px-8">
        <div className="text-[11.5px] font-semibold tracking-[0.08em] text-ok uppercase">Tur tamamlandı</div>
        <h2 className="mt-1 text-[20px] font-semibold tracking-[-0.02em] text-fg">Nereden başlamalı?</h2>
        <p className="mt-1 text-[13px] text-fg-muted">
          Üç adımda ilk raporunuzu alırsınız. Şu an {doneCount}/{items.length} hazır.
        </p>
      </div>
      <ol className="flex flex-col divide-y divide-line">
        {items.map((it, i) => (
          <li key={it.title} className="flex items-center gap-4 px-6 py-4 sm:px-8">
            <span
              className={cn(
                'flex size-9 shrink-0 items-center justify-center rounded-full border text-[13px] font-semibold [&_svg]:size-4',
                it.done ? 'border-ok/40 bg-ok-soft text-ok' : 'border-line-strong bg-surface-2 text-fg-muted',
              )}
            >
              {it.done ? <Check strokeWidth={2.5} /> : i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[13.5px] font-semibold text-fg">
                {it.title}
                {it.optional && <span className="rounded bg-surface-3 px-1.5 py-px text-[10.5px] font-medium text-fg-muted">İsteğe bağlı</span>}
                {it.done && <span className="text-[11.5px] font-medium text-ok">Hazır</span>}
              </div>
              <p className="mt-0.5 text-[12.5px] text-fg-muted">{it.body}</p>
            </div>
            <Button variant={it.done ? 'ghost' : 'secondary'} size="sm" onClick={() => go(it.to)} className="shrink-0">
              {it.cta}
              <ArrowRight className="size-3.5" />
            </Button>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2/40 px-6 py-3.5 sm:px-8">
        <span className="text-[12px] text-fg-muted">Turu sağ üstteki ? düğmesinden yeniden açabilirsiniz.</span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" onClick={onReplay}>
            Baştan izle
          </Button>
          <Button variant="primary" onClick={onClose} data-autofocus>
            Kullanmaya başla
          </Button>
        </div>
      </div>
    </div>
  );
}
