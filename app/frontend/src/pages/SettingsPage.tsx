import {useState} from 'react';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {Bot, Check, CircleCheck, CircleHelp, CircleX, ListRestart, Moon, Palette, Save, Sun, Zap} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk, useLlmSettings} from '@/hooks/queries';
import {useTheme} from '@/hooks/theme';
import {cn} from '@/lib/utils';
import type {LlmSettings, LlmSettingsInput} from '@/types';
import {openTour} from '@/lib/tour';
import {PageHeader} from '@/components/layout/AppShell';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button} from '@/components/ui/Button';
import {Field, Input} from '@/components/ui/Input';
import {Combobox} from '@/components/ui/Combobox';
import {SwitchRow} from '@/components/ui/Switch';
import {Badge} from '@/components/ui/Badge';
import {ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';

export function SettingsPage() {
  const query = useLlmSettings();
  return (
    <div className="animate-fade-in">
      <PageHeader title="Ayarlar" description="LLM tabanlı kurallar için model bağlantısı ve arayüz tercihleri." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card data-tour="llm-settings">
          <CardHeader
            icon={<Bot className="size-4" />}
            title="LLM ayarları"
            description="OpenAI uyumlu herhangi bir uç nokta (OpenAI, Azure OpenAI proxy, Ollama, LM Studio, vLLM…)"
            actions={
              query.data && (
                <Badge tone={query.data.enabled ? 'ok' : 'neutral'}>{query.data.enabled ? 'Etkin' : 'Devre dışı'}</Badge>
              )
            }
          />
          {query.isPending ? (
            <div className="grid gap-4 p-5">
              {Array.from({length: 4}).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : query.isError ? (
            <ErrorState error={query.error} onRetry={() => query.refetch()} title="LLM ayarları yüklenemedi" />
          ) : (
            <LlmForm key={query.dataUpdatedAt} settings={query.data} />
          )}
        </Card>
        <AppearanceCard />
      </div>
    </div>
  );
}

function LlmForm({settings}: {settings: LlmSettings}) {
  const [form, setForm] = useState<LlmSettingsInput>({
    enabled: settings.enabled,
    base_url: settings.base_url,
    model: settings.model,
    api_key: '',
    temperature: settings.temperature,
    timeout_seconds: settings.timeout_seconds,
    chunk_lines: settings.chunk_lines ?? 250,
  });
  const set = <K extends keyof LlmSettingsInput>(key: K, value: LlmSettingsInput[K]) => setForm((f) => ({...f, [key]: value}));
  const client = useQueryClient();
  const feedback = useFeedback();
  const payload = (): LlmSettingsInput => ({
    ...form,
    api_key: form.api_key ? form.api_key : null,
    temperature: Number(form.temperature) || 0,
    timeout_seconds: Number(form.timeout_seconds) || 120,
    chunk_lines: Math.min(2000, Math.max(50, Number(form.chunk_lines) || 250)),
  });
  const test = useMutation({mutationFn: () => api.llm.test(payload())});
  const models = useMutation({mutationFn: () => api.llm.models(payload())});
  const modelList = models.data?.models ?? [];
  const modelHint = models.isPending
    ? 'Modeller getiriliyor…'
    : models.data?.error
      ? undefined
      : models.data
        ? `${modelList.length} model bulundu; listeden seçebilirsiniz.`
        : 'Sunucudaki modelleri görmek için listeleyin.';
  const save = useMutation({
    mutationFn: () => api.llm.update(payload()),
    onSuccess: (data) => {
      client.setQueryData(qk.llm, data);
      feedback.success('LLM ayarları kaydedildi');
    },
    onError: (e) => feedback.error('Ayarlar kaydedilemedi', e),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid gap-4 p-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <SwitchRow
            title="LLM kurallarını etkinleştir"
            description="Kapalıyken LLM türündeki kurallar analizlere dahil edilemez."
            checked={form.enabled}
            onChange={(v) => set('enabled', v)}
          />
        </div>
        <Field label="Base URL" className="sm:col-span-2" hint="Örn. https://api.openai.com/v1 veya http://localhost:11434/v1">
          <Input mono value={form.base_url} onChange={(e) => set('base_url', e.target.value)} placeholder="https://api.openai.com/v1" />
        </Field>
        <Field label="Model" hint={modelHint} error={models.data?.error ?? (models.isError ? errorMessage(models.error) : undefined)}>
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <Combobox
                mono
                value={form.model}
                onChange={(v) => set('model', v)}
                options={modelList}
                onOpen={() => {
                  if (!models.data && !models.isPending && form.base_url) models.mutate();
                }}
                placeholder="gpt-4o-mini"
                emptyText={models.isPending ? 'Modeller getiriliyor…' : 'Model listesi için “Listele”ye basın.'}
              />
            </div>
            <Button
              type="button"
              variant="secondary"
              loading={models.isPending}
              icon={<ListRestart className="size-3.5" />}
              onClick={() => models.mutate()}
              disabled={!form.base_url}
              title="Sunucudaki modelleri listele"
            >
              Listele
            </Button>
          </div>
        </Field>
        <Field label="API anahtarı" hint={settings.has_api_key ? 'Kayıtlı bir anahtar var; boş bırakılırsa korunur.' : 'Yerel modeller için boş bırakılabilir.'}>
          <Input
            type="password"
            mono
            value={form.api_key ?? ''}
            onChange={(e) => set('api_key', e.target.value)}
            placeholder={settings.has_api_key ? '••••••••••••' : 'sk-…'}
            autoComplete="off"
          />
        </Field>
        <Field label="Sıcaklık (temperature)" hint="0 = deterministik, tekrarlanabilir sonuçlar">
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={form.temperature}
              onChange={(e) => set('temperature', Number(e.target.value))}
              className="h-1 flex-1 cursor-pointer accent-[var(--color-accent)]"
            />
            <div className="w-20 shrink-0"><Input mono className="text-right" type="number" step={0.05} min={0} max={2} value={form.temperature} onChange={(e) => set('temperature', Number(e.target.value))} /></div>
          </div>
        </Field>
        <Field label="Zaman aşımı (saniye)" hint="Her LLM çağrısı (her parça) için ayrı uygulanır.">
          <Input mono type="number" min={5} max={3600} value={form.timeout_seconds} onChange={(e) => set('timeout_seconds', Number(e.target.value))} />
        </Field>
        <Field
          label="Parça büyüklüğü (satır)"
          hint="Bu satır sayısını aşan nesneler LLM'e parçalar hâlinde gönderilir (50–2000). Küçük değer daha hızlı ve kararlı, büyük değer daha fazla bağlam demektir."
        >
          <Input mono type="number" min={50} max={2000} step={50} value={form.chunk_lines ?? 250} onChange={(e) => set('chunk_lines', Number(e.target.value))} />
        </Field>
        {(test.data || test.error) && (
          <div
            className={cn(
              'flex animate-fade-in items-start gap-2 rounded-lg border px-3 py-2.5 text-xs sm:col-span-2',
              test.data?.ok ? 'border-ok/30 bg-ok-soft' : 'border-bad/30 bg-bad-soft',
            )}
          >
            {test.data?.ok ? <CircleCheck className="mt-px size-3.5 text-ok" /> : <CircleX className="mt-px size-3.5 text-bad" />}
            <div className="min-w-0">
              <p className="font-medium text-fg">{test.data?.ok ? 'Model yanıt verdi' : 'Test başarısız'}</p>
              <p className="mt-0.5 break-words text-fg-muted">{test.data ? test.data.message : errorMessage(test.error)}</p>
              {test.data?.latency_ms !== null && test.data?.latency_ms !== undefined && (
                <p className="mt-0.5 text-fg-subtle tnum">Gecikme: {test.data.latency_ms} ms</p>
              )}
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-2/30 px-5 py-3">
        <Button className="mr-auto" loading={test.isPending} icon={<Zap className="size-3.5" />} onClick={() => test.mutate()} disabled={!form.base_url}>
          Bağlantıyı test et
        </Button>
        <Button type="submit" variant="primary" loading={save.isPending} icon={<Save className="size-3.5" />}>
          Kaydet
        </Button>
      </div>
    </form>
  );
}

function AppearanceCard() {
  const {theme, setTheme} = useTheme();
  const options = [
    {value: 'dark' as const, label: 'Koyu', icon: <Moon className="size-4" />},
    {value: 'light' as const, label: 'Açık', icon: <Sun className="size-4" />},
  ];
  return (
    <Card className="self-start">
      <CardHeader icon={<Palette className="size-4" />} title="Görünüm" description="Tercih bu tarayıcıda saklanır." />
      <div className="grid grid-cols-2 gap-3 p-4">
        {options.map((o) => {
          const active = theme === o.value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => setTheme(o.value)}
              aria-pressed={active}
              className={cn(
                'group overflow-hidden rounded-xl border text-left transition-all duration-150',
                active ? 'border-accent ring-3 ring-accent/25' : 'border-line-control/60 hover:border-fg-subtle',
              )}
            >
              <div className={cn('h-20 p-2.5', o.value === 'dark' ? 'bg-[#0b0d11]' : 'bg-[#f3f4f7]')}>
                <div className={cn('flex h-full gap-1.5 rounded-md p-1.5', o.value === 'dark' ? 'bg-[#13161c]' : 'bg-white shadow-sm')}>
                  <div className={cn('w-5 rounded', o.value === 'dark' ? 'bg-[#1c2028]' : 'bg-[#e9ebf0]')} />
                  <div className="flex flex-1 flex-col gap-1">
                    <div className={cn('h-1.5 w-2/3 rounded-full', o.value === 'dark' ? 'bg-[#2a2f3a]' : 'bg-[#d8dbe3]')} />
                    <div className="h-1.5 w-1/3 rounded-full bg-[#7c8cff]" />
                    <div className={cn('mt-auto h-4 rounded', o.value === 'dark' ? 'bg-[#1c2028]' : 'bg-[#eef0f4]')} />
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 border-t border-line px-3 py-2 text-[13px] font-medium text-fg">
                {o.icon}
                {o.label}
                {active && (
                  <span className="ml-auto flex size-4 items-center justify-center rounded-full bg-accent-solid text-white">
                    <Check className="size-2.5" strokeWidth={3} />
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
      <p className="px-4 pb-4 text-xs text-fg-subtle">
        İpucu: <span className="text-fg-muted">Ctrl/⌘ + K</span> ile komut paletinden de tema değiştirebilirsiniz.
      </p>
      <div className="flex items-center gap-3 border-t border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-fg">Tanıtım turu</div>
          <div className="text-xs text-fg-subtle">Demo ve ekran turunu yeniden izleyin.</div>
        </div>
        <Button size="sm" icon={<CircleHelp className="size-3.5" />} onClick={() => openTour()}>
          Başlat
        </Button>
      </div>
    </Card>
  );
}
