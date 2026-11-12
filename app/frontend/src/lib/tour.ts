import {safeStorageGet, safeStorageSet} from './utils';
import type {Severity} from '@/types';

/** Bump the suffix when the tour changes enough that everyone should see it again. */
export const TOUR_SEEN_KEY = 'dwhcr.tour.v1';
const OPEN_EVENT = 'dwhcr:open-tour';

export type TourStart = 'welcome' | 'demo' | 'spotlight';

export const tourSeen = () => safeStorageGet(TOUR_SEEN_KEY) === '1';
export const markTourSeen = () => safeStorageSet(TOUR_SEEN_KEY, '1');

/** Opens the tour from anywhere (header button, command palette, settings). */
export function openTour(start: TourStart = 'welcome') {
  window.dispatchEvent(new CustomEvent<TourStart>(OPEN_EVENT, {detail: start}));
}

export function onOpenTour(handler: (start: TourStart) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<TourStart>).detail ?? 'welcome');
  window.addEventListener(OPEN_EVENT, listener);
  return () => window.removeEventListener(OPEN_EVENT, listener);
}

/** One stop of the guided walk: the page to open, the element to light up and what to say. */
export interface SpotlightStep {
  key: string;
  route: string;
  /** `data-tour` value of the element to light up; null centres the bubble. */
  target: string | null;
  title: string;
  body: string;
  /** Short bullet points under the body. */
  points?: string[];
  /** Which side of the target the bubble prefers. */
  side?: 'right' | 'bottom' | 'left' | 'top';
}

export const SPOTLIGHT_STEPS: readonly SpotlightStep[] = [
  {
    key: 'nav',
    route: '/',
    target: 'nav',
    side: 'right',
    title: 'Menü üç bölümden oluşur',
    body: 'Analiz bölümünde çalıştırır ve sonuçları izlersiniz. Kural Seti denetlenecek standartları, Yapılandırma ise SQL Server ve LLM bağlantılarını tutar.',
  },
  {
    key: 'connections',
    route: '/connections',
    target: 'connections-new',
    side: 'bottom',
    title: '1. adım: SQL Server bağlantısı',
    body: 'Her şey bir bağlantıyla başlar. Sunucu adı, SQL istemci alias’ı veya host,port yazabilirsiniz.',
    points: ['Parola şifreli saklanır, arayüze geri gönderilmez', 'Kaynak veritabanına yalnızca okuma yapılır', '“Test et” ile bağlantıyı hemen doğrulayın'],
  },
  {
    key: 'llm',
    route: '/settings',
    target: 'llm-settings',
    side: 'left',
    title: 'İsteğe bağlı: LLM modeli',
    body: 'Anlamsal kurallar ve kural asistanı için OpenAI uyumlu bir uç nokta (LM Studio, Ollama, vLLM…) tanımlayın. LLM olmadan da regex ve yerleşik kurallar çalışır.',
    points: ['Büyük prosedürler parçalara bölünerek gönderilir', 'Model listesi sunucudan otomatik gelir'],
  },
  {
    key: 'rules',
    route: '/rules',
    target: 'rules-table',
    side: 'top',
    title: 'Kural seti: ekip standartlarınız',
    body: 'Kurallar üç türdür: regex (anında), yerleşik kontrol (SQL ayrıştırma + katalog metadatası) ve LLM (anlamsal). Her kuralın önem derecesi, kapsamı ve canlı test örneği vardır.',
    points: ['Kural editöründe örnek SQL ile anında test edin', 'Yanlış alarmları istisna tanımlayarak susturun'],
  },
  {
    key: 'assistant',
    route: '/rules',
    target: 'rules-assistant',
    side: 'bottom',
    title: 'LLM ile kural oluşturun',
    body: 'Ne denetlenmesini istediğinizi yazın, birkaç örnek verin. Asistan mevcut kurallarla karşılaştırır, taslak çıkarır, örneklerinizle doğrular ve gerçek nesnelerde gürültü testi yapar. Kaydetmeden önce onayınızı ister.',
  },
  {
    key: 'groups',
    route: '/rule-groups',
    target: 'groups-new',
    side: 'bottom',
    title: 'Kural grupları',
    body: 'Birlikte çalışan kuralları gruplayın (ör. “Hızlı Tarama (LLM’siz)”, “DM Katmanı”). Yeni analizde bir grubu tek tıkla seçersiniz.',
  },
  {
    key: 'wizard',
    route: '/analyses/new',
    target: 'wizard-steps',
    side: 'bottom',
    title: 'Analiz dört adımda başlar',
    body: 'Kaynak → Nesne havuzu → Kurallar → Özet. Havuzda nesneleri veritabanı, şema, tür, oluşturma/değişiklik tarihi ve ada göre filtrelersiniz; tüm filtreler VE ile birleşir.',
    points: ['Havuz × kurallar = kontrol sayısı; özet ekranında görürsünüz', 'Analiz arka planda adım adım ilerler'],
  },
  {
    key: 'analyses',
    route: '/analyses',
    target: 'analyses-table',
    side: 'top',
    title: 'Sonuçlar ve rapor',
    body: 'Çalışan analizler canlı güncellenir. Detayda bulguları önem, kural ve nesneye göre gezer; kodda ilgili satırı görürsünüz.',
    points: ['Tek tıkla HTML rapor veya CSV indirin', 'Bulgudan istisna oluşturup bir sonraki analizde gizleyin'],
  },
  {
    key: 'schedules',
    route: '/schedules',
    target: 'schedules-table',
    side: 'top',
    title: 'Zamanlanmış artımlı tarama',
    body: 'Kapsamı ve kuralları bir kez tanımlayın; sistem belirlediğiniz periyotta yalnızca değişen veya yeni nesneleri analiz eder ve önceki çalıştırmaya göre yeni/çözülen bulguları gösterir.',
  },
  {
    key: 'dashboard',
    route: '/',
    target: 'dashboard-kpis',
    side: 'bottom',
    title: 'Genel bakış',
    body: 'Toplam bulgu, önem dağılımı, en çok bulgu üreten kurallar ve trend tek ekranda. Kod kalitesinin zaman içinde nasıl değiştiğini buradan izlersiniz.',
  },
  {
    key: 'palette',
    route: '/',
    target: 'palette',
    side: 'bottom',
    title: 'Her yere Ctrl+K ile ulaşın',
    body: 'Komut paletiyle sayfalar, kurallar ve analizler arasında klavyeden gezinin. Bu turu istediğiniz zaman soru işareti düğmesinden yeniden açabilirsiniz.',
  },
];

/* ------------------------------------------------------------------ demo */

/** A small load procedure with typical DWH mistakes; the demo runs the real rule set over it. */
export const DEMO_OBJECT = {database: 'EDWDM', name: 'DMT.ins_DemoCustomerDaily', type: 'PROCEDURE' as const};

export const DEMO_SQL = `CREATE PROCEDURE DMT.ins_DemoCustomerDaily
    @DataDate DATE
AS
BEGIN
    SELECT *
    INTO #Customer
    FROM EDW.CUS.Customer
    WHERE ISNULL(CustomerTypeId, 0) = 1

    INSERT INTO DMT.CustomerDaily (CustomerId, Balance, EdwEtlDate)
    SELECT c.CustomerId, SUM(b.Balance), GETDATE()
    FROM #Customer c WITH (NOLOCK)
    LEFT JOIN EDW.ACC.Balance b ON b.CustomerId = c.CustomerId
    INNER JOIN EDW.COR.Branch br ON br.BranchId = b.BranchId
    WHERE b.EdwStatus = 1
      AND CONVERT(DATE, b.TransactionDate) = @DataDate
    GROUP BY c.CustomerId
END`;

export interface DemoFinding {
  code: string;
  name: string;
  severity: Severity;
  line: number | null;
  snippet: string;
  message: string;
}

/**
 * What the demo shows if the backend cannot be reached (captured from the shipped rule set), so
 * the walkthrough never dead-ends on a first run.
 */
export const DEMO_FALLBACK: DemoFinding[] = [
  {code: 'DWH-PF-03', name: 'EdwEtlDate/PersonnelFlag alanına insert yapılmış', severity: 'high', line: 10, snippet: 'INSERT INTO DMT.CustomerDaily (CustomerId, Balance, EdwEtlDate)', message: 'EdwEtlDate/PersonnelFlag alanına insert yapılmış'},
  {code: 'DWH-NOLOCK-02', name: 'Temp tablo okumasında NOLOCK/TABLOCK kullanılmış', severity: 'critical', line: 12, snippet: 'FROM #Customer c WITH (NOLOCK)', message: 'Temp tablo okumasında NOLOCK/TABLOCK kullanılmış'},
  {code: 'DWH-JOIN-01', name: 'LEFT JOIN’den sonra INNER JOIN kullanılmış', severity: 'high', line: 14, snippet: 'INNER JOIN EDW.COR.Branch br ON br.BranchId = b.BranchId', message: "LEFT JOIN'den sonra INNER JOIN: EDW.COR.Branch"},
  {code: 'DWH-SCD-02', name: 'EdwStatus ile kayıt filtrelenmiş', severity: 'critical', line: 15, snippet: 'WHERE b.EdwStatus = 1', message: 'EdwStatus ile kayıt filtrelenmiş'},
  {code: 'DWH-PERF-01', name: 'Join veya filtre kolonunda dönüşüm/fonksiyon kullanılmış', severity: 'high', line: 16, snippet: 'AND CONVERT(DATE, b.TransactionDate) = @DataDate', message: 'Filtre kolonunda fonksiyon: CONVERT(DATE, b.TransactionDate)'},
  {code: 'DWH-CAL-01', name: 'Tarih kolonu dönüştürülerek filtrelenmiş', severity: 'low', line: 16, snippet: 'AND CONVERT(DATE, b.TransactionDate) = @DataDate', message: 'Öneri: CONVERT(DATE, b.TransactionDate) yerine EDW.COR.Calendar ile aralık join’i kullanın'},
];
