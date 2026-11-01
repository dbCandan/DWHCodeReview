---
id: "13-tamamlanma-tanimi"
title: "Yalnızca gerçekten ulaşılan kanıt seviyesini iddia et"
scope: process
authority: mandatory
priority: 40
trigger: always
applies_to: []
gate: "done_report"
---

# Kanıt seviyeli tamamlanma tanımı

Kanıt seviyeleri birikimlidir:

- **L0 — Yazıldı, henüz çalıştırılmadı:** gerekli kod, yapılandırma, şema yetkisi, göç,
  spesifikasyon veya belgeleme vardır. Odaklı ya da kısmi test çalışmış olsa bile ilgili tam otomatik
  kapı geçmediyse tamamlanma seviyesi L0'da kalır.
- **L1 — Otomatik testlerden geçti:** güncel değişiklik kümesi için ilgili ürünün tam otomatik kapısı;
  geçerli biçim, `lint`, tip, birim, tümleştirme, sözleşme ve üretilmiş yapıt kontrolleriyle eksiksiz
  geçmiştir.
- **L2 — Gerçek istemci/ortamda doğrulandı:** L1'e ek olarak davranış alana uygun gerçek istemci,
  `HTTP`, tarayıcı, MCP veya çalışma ortamı sınırında gözlemlenmiştir.
- **L3 — Sorumlu sahibi kabul etti:** L2'ye ek olarak sorumlu insan sahibi belirli kapsamı ve bağlı
  kanıtı açıkça kabul etmiştir.

Bu ürün taksonomisi yalnız kararlı `L0`, `L1`, `L2`, `L3` makine kodlarını kabul eder; `L4` geçerli
bir tamamlanma seviyesi değildir.

Gerçekten gözlemlenen en yüksek seviyeyi belirt. Kod incelemesinden geçiş sonucu çıkarma, atlanan
adımı geçmiş sayma veya mevcut kanıta uyması için iddiayı sessizce düşürme. `done_report` öneri
niteliğindedir: desteklenmeyen iddia için başarı dönebilir; ancak eksik kanıtı listelemeli ve boşluğu
devir raporuna taşımalıdır.

Önceki bir kanıt yalnız güvenilen bir doğrulayıcı tarafından gerçekten doğrulanmışsa ve bağlı olduğu
exact değişiklik ağacı veya input snapshot'ı ile proje kimliği, yönetişim otoritesi ve yürütme bileşimi
güncel durumla birebir eşleşiyorsa yeniden kullanılabilir. Repo-local, değiştirilebilir bir makbuz bu
güven sınırını kendi beyanıyla kurmaz; bilgilendirme kaydı olarak kalır. Bayat, kısmi, doğrulanmamış
veya farklı snapshot/bileşime ait makbuz L0'ın üstünü desteklemez.

Kanıt seviyesi; Agent aktivasyonu, çalışma zamanı uygunluğu, kurumsal kabul, production admission,
dağıtım veya sertifikasyon anlamına gelmez. Bunlar ayrıca yetkili kanıt gerektirir.

“Tamamlandı” ayrıca kabul edilmiş `PRD`'nin gerektirdiği tüm katmanların birlikte teslim edildiği ve
üretilmiş sözleşmelerin güncel olduğu anlamına gelir. Çalıştırılamayan her testi, canlı akışı, işçiyi,
göçü, `chart`'ı veya ortam denetimini ve nedenini adlandır. Dürüst L1 geçerlidir; çalıştırılmamış
L2 ve insan kararı olmayan L3 iddiası geçerli değildir.

Mevcut PRD yetkisinin yeniden kullanıldığı teslimde rapor; PRD yolunu, exact `Requirement <n>` ve
`Acceptance <n>` kimliklerini, ilgili mevcut `tasks.md` görevini ve güncel koşum/kanıt makbuzunu taşır.
Bu izlerden biri yoksa küçük değişiklik iddiası yeni PRD üretmez; yetki yeniden kullanımını reddeder ve
önce mevcut PRD revizyonu gerekip gerekmediğini bildirir.

Tamamlanma, koşum ve inceleme sonucunu kişiye `02-iletisim-tarzi` kuralındaki sade dil sözleşmesiyle
anlat; kanıt seviyesi kodunu yukarıdaki sade adıyla birlikte yaz.

## Governed-review çağrı yönlendirmesi

Önce proje kökünde ayrı komut olarak
`python3 .kt-scaffold/hooks/governance_client.py preflight` çalıştır. Bu ön kontrol
repo dışındaki ortak yönetişim kökünü, yazılabilirliğini, projenin `.venv` yorumlayıcısının
teknoloji profiliyle eşleşmesini ve projenin commit'i olan bir git deposunda (projenin değişiklik
geçmişini tutan kayıt) bulunmasını denetler; kayıt okumaz ve hiçbir şeyi değiştirmez. Başarılı
`ok:true` yalnız bu kontrollerin sonucudur; makbuz, kalıcı yazım, native uygulatım veya review
`PASS` kanıtı değildir. Komut yoksa, çalıştırılamıyorsa veya `ok:false` dönerse snapshot/uzman
çağrısından önce `BLOCKED_INCOMPLETE` ile dur ve `root_status`, `interpreter_status` ile
`repository_status` kodlarını raporla. `repository_status` `not-a-repository` veya `no-commit` ise
ilk kurulumun git adımı (kural 03) tamamlanmamıştır; bunu kullanıcıya
sade dille söyle, depoyu kendin açıp commit oluşturma. Kökü repo'ya veya HOME'a taşıma, kontrolü
atlama.
Ön kontrol geçse bile bu submission'a bağlı metadata ayrıca doğrulanır. Metadata yoksa
`PROMPT_METADATA_MISSING` ve `BLOCKED_INCOMPLETE` raporla; seçili istemcinin native kanca
keşfi, güven onayı, etkinlik ve son prompt olayını kontrol et. Dosyanın bulunması veya projenin
trusted olması native yürütüm kanıtı değildir. Sorun çözüldükten sonra yeni gerçek prompt olayı
gerekir; önceki promptu yeniden oynatarak veya elle metadata yazarak kanıt üretme.
"Kapı açık" deme; "Yönetilen inceleme (değişiklik kaydedilmeden önceki uzman denetimi)
tamamlanamadı; bu yüzden değişiklik henüz kaydedilemez." diye bildir.

`governed-review`, bir supervisor veya tek istemci Agent'ı değildir;
`agent-platform/orchestrations/governed-review.yml` içindeki on iki zorunlu Agent raporunu ayrı
çağrılarda toplayan ve sürümlü `policy:governed-review-aggregation` ağırlık, eşik, öncelik ve
hard-fail kurallarını kullanan orkestrasyondur. Eksik, `failed`, `timeout` veya `invalid` rapor
`BLOCKED_INCOMPLETE` üretir.

Faz 1'de bulguları on iki uzman LLM üretir; kararı `governance_client.py finalize-review` sürümlü
toplama politikasını kodla uygulayarak üretir. Sonuç **Agentic pilot kararıdır**; belirlenimci,
canonical-conformant, runtime-admitted, production-authoritative veya değişmez audit kanıtı
değildir. `GovernanceAssessmentReport` sözleşmesi gevşetilmez; Faz 1 makbuzu raporların
Agentic olarak gözlendiğini açıkça belirtir ve kendi kendine kanonik bütünlük yetkisi vermez.

Faz 1 yerel inceleme, inert projection kaydındaki `activation_status: not_activated` veya
ayrı runtime/conformance adayına ait `client_version_range` nedeniyle tek başına durmaz.
Bunlar kurumsal aktivasyon/kabul iddiasını sınırlar; yerel Agentic incelemeye yeni admission
ön koşulu eklemez. Seçili native Agent gerçekten çağrılabilir olmalı; gerçek istemci sürümü,
projection ve bileşen digest'leri gözlenip bağlanmalıdır. Bu alanları etkin/admitted göstermek
için değiştirme. Uzman bulgularına `policy:governed-review-agentic-evaluation` uygulanır;
eksik veya geçersiz gerçek gözlem yine `BLOCKED_INCOMPLETE` üretir.

Seçili istemcinin yerel `governed-review` becerisini şu durumlarda kullan:

- kullanıcı açıkça yönetilen inceleme istediğinde;
- PR veya teslim hazırlığında;
- değişiklik birden fazla risk ya da uzmanlık alanını etkilediğinde;
- otorite, politika veya manifest bileşimi değiştiğinde;
- commit kapısı `GOVERNED_REVIEW_REQUIRED` döndürdüğünde.

Her prompt veya Agent turunda, her küçük TDD adımında ya da değişmemiş snapshot için körlemesine tam
review çalıştırma. Prompt/session olayı eylem yetkisini yeniler; tek başına teknik kanıtı geçersiz
kılmaz. Stable `project_id`, exact input/Git-index tree ile `HEAD`/merge-parent bağlamı,
güncel otorite özeti, on iki Agent/policy/detector bileşimi, istemci, orkestrasyon, karar
politikası, evaluator/harness, prompt template/envelope ve context/retrieval/tool-result manifest
digest'leri birebir aynıysa eksiksiz Faz 1 Agentic `PASS` makbuzu yalnız aynı commit adayının retry
denemesinde yeniden kullanılabilir. İstemci kimliği/sürümü/digest'i zorunlu `audit_replay`
bağıdır. Etkin model ve effort'u istemci bildirir ve prompt kancası bunları prompt kaydına yazar:
Codex ve Cursor modeli her kanca olayında, Cursor effort'u model parametrelerinde taşır; Claude Code
modeli oturum logunda, effort'u araç olaylarında verir; VS Code/Copilot modeli bildirmez. Receipt
`execution.model` alanında bağlı prompt kaydının model nesnesini aynen taşır. Commit kancası bu
nesneyi prompt kaydıyla ve commit anında istemcinin bildirdiği modelle karşılaştırır; model
değiştiyse yeni review gerekir. Sağlayıcı, deployment, model sürümü, digest veya başka inference
parametresi istemci tarafından gözlenemiyorsa değer uydurulmaz; typed `unavailable` + reason
kaydedilir ve yalnız best-effort `model_rerun` unavailable kalır. Modelin gözlenememesi ve bu
optional model-rerun metadata eksikliği, doğrulanmış `audit_replay` kararını tek başına
`BLOCKED_INCOMPLETE` yapmaz. Zorunlu audit binding'lerinden biri
değişirse kanıt bayattır ve gerekli profile göre review yenilenir;
yalnız yakın zamanda üretilmiş olması reuse yetkisi vermez.

Aynı reuse identity için tek aktif run/lease vardır. Aktif koşuma katıl; yarıda kalan koşumu aynı
`run_id` ile `review-start` komutunu yeniden çalıştırarak sürdür ve yalnız raporu eksik uzmanları
çağır. Decision ve run receipt hazır, audit veya current yayını eksikse uzmanları ve testleri yeniden
çalıştırma; yalnız canonical finalizer'ı yeniden çağır. Normal commit
`commit-fast`, dependency/config değişikliği `risk-escalated`, PR/release ise `full` profil ister.
Receipt şeması profil bilgisi taşımaz ve yalnız full on iki-Agent kanıtını temsil eder; dar profil
koşumunu on iki-Agent `PASS` olarak sunma.

Test kanıtını `offline`, `shared-boundary`, `browser` ve `live-model` lane'lerinde ayrı tut. Her
lane `PASS`, `FAIL`, `TIMEOUT`, `INTERRUPTED` veya `INCOMPLETE` olur; yalnız exact snapshot,
toolchain, dependency ve command digest'lerine bağlı temiz `PASS` manifesti reuse edilir. Süre ve
retry bütçesi manifestte bulunur; bütçe aşımını yeniden başlatma döngüsüne çevirme.

Bir engel `stage`, artifact `path`, `field`, `expected`, `observed`, iki çelişen kaynak,
`responsible_repository`, en küçük uygulanabilir `remediation` ve `full_review_required` alanlarıyla
raporlanır. Teknoloji/politika/template kusuru fabrikaya; uygulama, lock ve ürün davranışı tüketici
repoya atanır. Canonical sahiplik defteri
`docs/tr/referans/governed-review-sahiplik-defteri.md` içindedir.

Native commit kancası görünür ve desteklenen doğrudan Git/shell sözdiziminde exact staged adayın
Faz 1 makbuzunu denetler. Native Agent/prompt kancasını gerçekten destekleyen ve pinned L2 kanıtı
bulunan istemcide kanca, LLM ile yalnız makbuzun aynı snapshot'a ait `PASS` sonucunu gözleyebilir;
on iki uzman Agent'ı kanca içinde yeniden çağırmaz. Eksik veya bayat makbuzda
`GOVERNED_REVIEW_REQUIRED` ile reddeder; normal ana Agent turu beceriyi çalıştırır, gerekli profil
kanıtını ve karar/audit kaydını üretir ve yalnız aynı staged aday için commit yeniden denenir.
Tek istisna, koşulları `03-is-akisi-hijyeni` kuralında tanımlı projenin ilk iskelet commit'idir
(`INITIAL_SCAFFOLD_COMMIT`); kanca bu commit için makbuz üretmez ve koşullardan biri eksikse olağan
denetimi uygular.
Doğrudan commit denetimi deny durumunda başlar ve yalnız bütün zorunlu gözlemler başarıyla
tamamlanırsa allow döndürür. Git plumbing, `Read`/dosya, permission, tool, parse, schema,
canonicalization, digest, snapshot, timestamp veya ikinci-geçiş recalculation hatası; unavailable,
denied, gerekli metadata için parça okumayla da tamamlanamayan truncated ya da belirsiz sonuç;
eksik/stale kanıt veya tam reuse nesnesinin kurulamaması `BLOCKED_INCOMPLETE` üretir. Başarısız gözlemi receipt beyanı, bellek, tahmin veya indirgenmiş JSON
ile ikame etmek yasaktır.

Client matcher yalnız coarse tetikleyicidir. Dependency-free command harness sadece top-level
executable doğrudan `git` veya `/usr/bin/git`, desteklenen Git global flag'leri ve gerçek Git
subcommand'i `commit` olduğunda makbuz denetimine geçer. `git` ile `commit` arasında yalnız sabit
güvenli global bayraklar bulunabilir: `--no-pager`, `--paginate`, `--no-optional-locks`,
`--no-replace-objects`, `--no-lazy-fetch`, `--literal-pathspecs`, `--glob-pathspecs`,
`--noglob-pathspecs`, `--icase-pathspecs`. `commit` sonrasındaki her seçenek staged tree'yi
değiştirmeyen sabit izin listesinden olmalıdır: mesaj ve yeniden kullanım (`-m/--message`,
`-F/--file`, `-C/--reuse-message`, `-c/--reedit-message`), `--author`, `--date`, `--cleanup`,
`--template`, `--trailer`, `--untracked-files`, imza (`-s/--signoff`, `--no-signoff`,
`-S/--gpg-sign`, `--no-gpg-sign`), düzenleme (`-e/--edit`, `--no-edit`), `--allow-empty`,
`--allow-empty-message`, `-n/--no-verify`, `--no-post-rewrite`, `--dry-run` ve durum çıktısı
biçimi (`-q/--quiet`, `-v/--verbose`, `-z/--null`, `--status`, `--no-status`, `--short`, `--long`,
`--porcelain`, `--branch`, `--ahead-behind`, `--no-ahead-behind`, `--show-stash`,
`--no-show-stash`). Listede olmayan veya bilinmeyen her seçenek, değeri eksik kalan seçenek,
`--` ve pathspec artifact okumadan `UNSAFE_DIRECT_COMMIT_SHAPE` ile deny edilir. Kaynak/string veya heredoc içeriğinde salt
literal olarak geçen `git commit` ile kanıtlanmış basit non-commit argv, artifact/Git aracı okumadan
hemen geçirilir. Buna karşılık görünür leading-git shell expansion/composition; sonradan gerçek
`git commit` segmenti çalıştırabilen compound/pipeline/redirect/process-substitution; desteklenmeyen
repo-yönlendiren Git global seçenekleri ve `command`, `env`, `sudo`, `sh -c` gibi doğrudan commit
çalıştırabilen çözülebilir wrapper biçimleri belirsiz allow edilmez, artifact okumadan
`UNSAFE_DIRECT_COMMIT_SHAPE` ile deny edilir. Opaque alias/wrapper, manuel terminal ve Git GUI yine
native yüzey dışıdır ve bunlar için önleme iddiası kurulmaz. Görünür doğrudan
`git commit --no-verify` ise bu native yüzeyde kalır; `--no-verify` yalnız Git hooklarını atlar.
Görünür `git commit -a/--all`,
`--include`, `--only`, `--interactive`, `--patch`, `--pathspec-from-file` veya pathspec staged
snapshot'tan farklı tree seçebildiği için kapsam dışı allow edilmez; `UNSAFE_DIRECT_COMMIT_SHAPE`
ile deny edilir. Kapsam dışı wrapper biçimleri için evrensel enforcement veya fail-closed önleme
iddiası kurulmaz.

Normal ana Agent turu on iki uzmanı çağırır ve her uzmanın değiştirilmemiş değerlendirmesini
istemcinin native dosya aracıyla, repo dışındaki ortak yönetişim kökünde
`governance_client.py review-start` komutunun döndürdüğü koşum dizinindeki
`work/<agent-slug>-evaluation.json` dosyasına yazar. Koşum girdilerini `review-start`, uzman
raporlarını `observation`; kararı, receipt'i, audit zincirini ve yayın işaretini yalnız canonical
`finalize-review` komutu üretip yayımlar; Agent bunları elle kurmaz, argv içinde taşımaz veya
yeniden yazmaz. Uzman değerlendirmesi dışında artifact üretimi için Python/Node/interpreter,
heredoc, shell redirect, `tee`, `cp`, Bash `mkdir` veya compound Bash kullanılmaz; native yazma
mümkün değilse sonuç `BLOCKED_INCOMPLETE` kalır. Bash yalnız ayrı basit Git/sürüm gözlemleri ve
`governance_client.py` komutları içindir.

Bu reçetede Bash istemcinin terminal aracıdır; native dosya aracı istemcinin kendi dosya okuma ve
yazma aracıdır: Claude Code'da `Read` ile `Write`/`Edit`; Cursor ve VS Code/Copilot'ta istemcinin
dosya okuma ve düzenleme araçları. Codex'te yazma yalnız `apply_patch` ile yapılır ve ayrı bir okuma
aracı yoktur; Codex'te native okuma ayrı, basit ve salt-okunur kabuk komutudur: `cat <dosya-yolu>`,
`sed -n '<başlangıç>,<bitiş>p' <dosya-yolu>` veya `od -An -tx1 <dosya-yolu>`. Bu okuma artifact
üretimi değildir ve ortak kökteki kayıt dosyalarını açma yasağını kaldırmaz. Okuma aracının ayrı bir
adı olmaması `BLOCKED_INCOMPLETE` nedeni değildir. İstemci uzun bir okuma çıktısını kısaltarak
gösterirse aynı dosyanın gösterilmeyen kısmını daha küçük satır aralıklarıyla oku (Codex'te
`sed -n '<başlangıç>,<bitiş>p' <dosya-yolu>`). İçeriğin tamamı böyle gözlendiyse okuma eksiksizdir
ve kısaltılmış ilk görünüm `BLOCKED_INCOMPLETE` nedeni değildir; içeriğin tamamı gözlenemezse sonuç
truncated kalır ve `BLOCKED_INCOMPLETE` üretir. Uzman, çağrıda mutlak yolu verilen kendi
`inputs/<agent-slug>.bindings.json` dosyasını aynı yolla okur; ortak kökte başka dosya açmaz.

Koşumu tek ayrı komut açar: `python3 .kt-scaffold/hooks/governance_client.py review-start --run-id
<run_id> --client-id <client> --client-version <sürüm> --criteria-path <PRD yolu>`. Ajan yalnız
gözlediği istemci sürümünü ve `agent:test-otomasyonu` için kabul ölçütü olan PRD'nin repo-göreli
yolunu verir; PRD `specs/<alan>/PRDs/<nnn>-<yetenek>/PRD.md` biçiminde staged index'te bulunur,
`Version:` veya `Document version:` satırı taşır ve ilk `Status:` satırı `Accepted` ya da `Draft`
olur. Kriter kimliğini, sürümünü, özetini ve yaşam döngüsünü komut staged index'teki PRD'den
üretir: kabul edilmiş PRD `accepted-frozen`, taslak PRD `draft` olarak bağlanır; başka durum
`CRITERIA_STATUS_UNSUPPORTED` üretir, uygun PRD yoksa koşum `BLOCKED_INCOMPLETE` kalır. Taslak
PRD incelemeyi ve commit'i engellemez; karar, receipt ve karar kanıtı aynı bağı taşır ve commit
kancası bağı staged PRD'den yeniden türetir. Ajan PRD'nin durumunu değiştirmez; kabul PRD sahibinin
kararıdır. Sürüm satırı olmayan PRD `CRITERIA_VERSION_UNAVAILABLE` ile durur ve kanca sürüm
uydurmaz. Taslak (`Status: Draft`) PRD'de ajan kendisi `Status:` satırının altına boş bir satır ve
`Version: 0.1.0` satırını ekler; durumu ve başka hiçbir metni değiştirmez, yalnız bu dosyayı
`git add -- <PRD yolu>` ile stage eder ve aynı `review-start` komutunu yeniden çalıştırır.
Kabul edilmiş PRD'nin sürüm satırı eksikse ajan PRD'ye dokunmaz; koşum `BLOCKED_INCOMPLETE` kalır
ve satırı PRD sahibi ekler. Taslak bağ yalnız inceleme ve commit iznidir; `10-once-spesifikasyon` kuralındaki kabul
şartını, bu kuraldaki “Tamamlandı” tanımını ve kanonik `GovernanceAssessmentReport`, çalışma
zamanı ve üretim kabulünün `accepted-frozen` şartını değiştirmez. Komut exact Git-index
snapshot'ını (`git write-tree`, `HEAD` ve dosya sırası korunmuş `MERGE_HEAD` parent'ları; henüz
HEAD commit'i yoksa `head` JSON null, MERGE_HEAD yoksa `merge_heads` `[]`) `inputs/snapshot.json`
dosyasına; bu submission'ın prompt kaydını, istemci sürümünü, istemcinin bildirdiği model ve
effort'u, `receipt_id`, `trace_id` ile her çağrının `invocation_id` ve `span_id` değerlerini
`inputs/run.json` koşum bağlamına kanonik baytlarla bir kez yazar. Aynı `run_id` ile yeniden
çalıştırılan komut aynı girdileri doğrulayıp koşumu sürdürür; farklı istemci sürümü, kabul ölçütü
veya snapshot `run-conflict` üretir. Snapshot, korelasyon kimlikleri, evaluator ve Agent
bileşenleri için zorunlu bağlar tamamlanmadan uzman çağırma. Komut hata verirse `BLOCKED_INCOMPLETE`
ile dur; eksik bağlarla on iki geçersiz rapor toplama. Uzmanlar çağrıldıktan sonra index değişirse
eski raporların metadata'sını onarma; `finalize-review` `SNAPSHOT_CHANGED` ile reddeder ve yeni
koşum gerekir. İsteğe bağlı model metadata'sı için mevcut `unavailable` kuralı değişmez.

Uzman kimlik ve özet kopyalamaz. `review-start`, uzman değerlendirmesi olan `status`, `findings`,
`scanned_files`, `error_code` ve `error_summary` dışındaki bütün zorunlu gözlem alanlarını yetkili
kaynaklarından koşuma özel `inputs/<agent-slug>.bindings.json` dosyasına yazar; uzman dosyayı native
okuma yoluyla bağlam için okuyabilir. Çağrıda
bu dosyanın mutlak yolu, exact aday kapsamı ve çıktı sözleşmesi bulunur: uzman tek JSON nesnesi
olarak yalnız `agent_id`, `status`, `findings`, `scanned_files`, `error_code` ve `error_summary`
döndürür; bulgular `agent-platform/agentic-governance-observation.schema.json` şemasındaki
`finding` tanımına uyar. Orkestrasyondaki `execution.agent_isolation: true` gereği uzman ana
oturumun geçmişini ve başka uzmanların raporlarını görmez; Codex'te `spawn_agent` çağrısı
`fork_turns: "none"` taşır, varsayılan `all` geçmişi aktarır. Geçmiş aktarılan çağrının raporu
yalıtılmış sayılmaz. Ana Agent uzmanın yanıtını değiştirmeden `work/<agent-slug>-evaluation.json`
dosyasına yazar ve `governance_client.py observation --run-id <run_id> --agent <agent-slug>`
komutunu çalıştırır. Uzman bulguya kontrol kimliği (`controls`) yazmaz; talimatında geçen kaynak
kural kimlikleri bulgu alanı değildir. Komut değerlendirmeyi bağlama dosyasıyla bayt bayt
birleştirir, Agent politikasındaki kurum politikası bağlarını (`KT-AGENT-POLICY`) her bulguya
kendisi ekler, gözlem şemasıyla denetler ve raporu kanonik baytlarla bir kez yazar. Bulgunun nedenini
ve ISO/KVKK dayanağını kod ekler; kuralları
[bulgu dayanağı PRD'si](../specs/agent-platform/PRDs/009-finding-reason-and-iso-kvkk-basis/PRD.md)
belirler. Sözleşmeye uymayan yanıtı ana Agent
onarmaz. Komut yanıtı uzmanın düzeltebileceği bir red koduyla reddederse, kimliği yanlış yanıt
dahil, yanıt bu kod ve ihlal yeriyle yalnız o uzmana bir kez geri verilir; ikinci red veya başka
bir red `invalid` kaydıyla koşumu `BLOCKED_INCOMPLETE` bırakır. Sabit alanlar şemadan gelir;
`phase1-agentic-advisory` kısaltılamaz veya yeniden adlandırılamaz. Bağlama dosyası genel
prompt/transcript saklamaz; yalnız kimlik, sürüm, digest ve sözleşme metadata'sıdır.

Prompt makbuzunda `prompt_capture.text` zorunlu envelope girdisi değildir; bu metni okuma veya
kopyalama. `review-start` prompt bağını `python3 .kt-scaffold/hooks/governance_client.py
current-prompt-metadata --client-id <client>` komutunun kuralıyla seçer: allowlist vendor session
ortamını yalnız süreç belleğinde hash'ler, repo dışındaki ortak yönetişim kökünde aynı session'a ait
son tekil prompt kaydını seçer ve içeriksiz `PromptIngressMetadata` projeksiyonunu bağlar. Ham
session değeri çıktı veya kayda girmez; eksik, bozuk ya da belirsiz seçim `BLOCKED_INCOMPLETE`
bırakır.
`agent-platform/prompt-ingress-metadata.schema.json` sözleşmesi yalnız izinli
event/project/client/session/turn, decision/outcome, timestamp, kaynak makbuz başvurusu/digest'i
ve `prompt_capture_sha256` taşır; prompt metni, kullanıcı kimliği, reasoning veya log içermez.
Buradaki decision prompt taramasınındır, governed-review PASS kararı değildir.
`source_receipt_path` alanı tam `record:v1:<project_id>:prompt-ingress:<event-token>`
başvurusudur; `python3 .kt-scaffold/hooks/governance_client.py metadata --source-ref <ref>`
aynı kaydın projeksiyonunu döndürür. `finalize-review` envelope'u bu projeksiyondan kurar:
`source_receipt_sha256` kaynak makbuzun digest'idir, `prompt_capture_sha256` aynen bağlanır.
Genel `ls`/`cat`, keyfi Python yardımcısı veya caller-selected path kullanma; ortak kökteki kayıt
dosyasını native Read ile açma; yol uydurma. Eski/farklı tur, yanlış proje/istemci, değişen kaynak,
eksik veya bozuk metadata `BLOCKED_INCOMPLETE` üretir. Yerel metadata tur seçimi veya bağımsız
doğrulama yetkisi vermez. Eksik kaydı LLM üretmez, geçmiş kayıtları onarmaz, raw makbuz/satır
okumasına geri dönmez. Sabit fikstür satırı varsayma; kesik metinden hash üretimi isteme.

Koşum girdilerini, raporları, kararı ve receipt'i komutlar her iç nesnede anahtarları sıralı,
minified UTF-8 ve tek LF sonlu kanonik baytlarla bir kez yazar; ajan JSON baytı, özet veya digest
üretmez. Başka bir kurulumdan dönen PATH sürümünü etkin istemci sürümü olarak kaydetme; version
binding bu oturumu yürüten executable'a ait olmalıdır. Codex native oturumunda ayrı ve basit
`codex --version`, Claude Code oturumunda `claude --version` gözlemi kullanılır.

Native event/envelope istemci sürümünü taşımıyorsa etkin istemcinin native extension bilgisi
veya aynı etkin kurulumla bağı doğrulanmış yerel paket metadata'sı salt-okunur gözlenebilir.
Etkin host/extension yolu ile publisher/name/version alanlarını doğrula; başka kurulum,
devre dışı extension veya yalnız PATH sonucunu kullanma. Host IDE sürümünü Copilot sürümü
diye yazma. Birden fazla kurulum arasında etkin olanı ayıramıyorsan bağ belirsizdir ve
`BLOCKED_INCOMPLETE` kalır. Native Read veya ayrı salt-okunur metadata çıkarma komutu sürüm
gözlemidir; artifact/karar üretimi veya runtime kurulumu değildir. Sürüm/digest bağı zorunlu
kalmaya devam eder; tahmin, varsayılan sürüm veya optional model metadata istisnası bu bağın
yerine geçmez.

Cursor için `native-event-observed` kaynak ve gerçek event sürümü bağı korunur; yerel metadata
native event yerine geçirilemez. VS Code/Copilot yerel metadata gözlemi ise mevcut
`agent-self-observed` kaynak sınırında kalır; native event kanıtı diye yükseltilmez.

Faz 1 evaluator bir runtime veya on üçüncü custom Agent değildir. On iki ayrı gözlemden sonra
`governance_client.py finalize-review`; sürüm ve digest bağlı
`policy:governed-review-agentic-evaluation` sözleşmesini `code-policy-application` modunda kodla
uygular. Bu ayrı sözleşme ağırlık, severity bandı, eşik, öncelik, fail-closed ve hard-fail
değerlerini kopyalamaz; komut her koşumda güncel `policy:governed-review-aggregation` dosyasından
okur. Uzman severity etiketi ilgili kanonik bandın puanına eşlenir; Agent başına maksimum ve
normalize ağırlıklı ortalama hesaplanır. Uyarı eşiği `PASS` yanında `AGG_THRESHOLD_WARNING`, fail
eşiği `FAIL` üretir. Bilgi güvenliği, uygulama güvenliği veya KVKK Agent'ının güven tabanını geçen
`critical` bulgusu skor eşiğin altında kalsa bile `FAIL` ve `AGG_SECURITY_CRITICAL_VETO` üretir;
commit kancası bu vetoyu yeniden denetler. Serbest LLM `critical` etiketi hard-fail yetkisi
değildir; `HARD-FAIL` yalnız kural tabanlı taramadan gelir: kesin gruptaki detektörün kod bulgusu
veya uzmanın onayladığı zorunlu aday. Hangi detektörün hangi grupta olduğunu
`agent-platform/agents/<ajan>/detectors.yml` paketindeki `scan_group` alanı söyler; sonuç koşumun
`reports/deterministic-scan.json` kaydına yazılır ve `finalize-review` ile commit kancası taramayı
yeniden çalıştırır. Staged baytları `.kt-scaffold/manifest.json` kaydındaki özete birebir eşit
yönetilen dosya taranmaz ve kayıtta "taranmadı: otoriteyle birebir" diye listelenir. Çözülmemiş listedeki detektörün kod bulgusu veya `source-conflict:` kaynaklı
bulgu `AGG_AUTHORITATIVE_CONFLICT` ile `BLOCKED_INCOMPLETE` üretir.
Eksik kontrol/location/evidence, düşük confidence, belirsiz sınıflandırma, `failed`, `timeout` veya
`invalid` rapor ya da binding uyuşmazlığı `BLOCKED_INCOMPLETE` üretir. Öncelik
`BLOCKED_INCOMPLETE > HARD-FAIL > FAIL > PASS` sırasıdır. Kısa gerekçe sürümlü
`decision-explanation-templates.yml` şablonundan ilk gerekçe koduyla üretilir; diğer kodlar
eklenir.
Her uzman bulgusu staged değişiklikte gözlenen somut etki veya risk, uygulanabilir kanonik kontrol
ve konum/kanıt bağı taşımalıdır. Rolün `non_responsibilities` sınırları korunur; yalnız kişisel
stil tercihi veya kanıtsız varsayım bulgu değildir. Gerçek düşük güvenli bir bulguyu `PASS` elde
etmek için gizleme, silme veya `confidence` değerini yükseltme; böyle bir bulgu güncel
`confidence_floor` ve `fail_closed.low_confidence` uyarınca `BLOCKED_INCOMPLETE` üretir.
Anlamsal uzman bulgusu önem bandının puanıyla ajan puanına ve güvenlik vetosuna girer.

Faz 1 karar kaydının kanıt temeli bit-bit aynı LLM metni değil, bağlamı yeniden kurup kanıt
zincirini doğrulayabilen ve policy hesabını yeniden değerlendirebilen **Evidence-Bound Accountable
Replay** sözleşmesidir. Receipt tek bir sürümlü `decision_evidence` nesnesi taşır. Zorunlu
`audit_replay`; kanonik input + exact snapshot, authority, aggregation/evaluator policy,
Mandatory Governed Execution harness, bu kural, selected-client skill, on iki Agent component
manifesti, istemci, prompt-template/envelope ve context/retrieval/tool-result manifestlerini
version+digest ile bağlar.

Commit kancası beyan edilen digest'lere güvenmez; kanıt kökenlerini yeniden hesaplar.
`input_binding.canonical_input` tam olarak `canonicalization:
kt-agentic-review-input-manifest-json-v1`, `item_count: 1` ve `sha256: <snapshot_sha256>`
alanlarından oluşur; farklı değer `CANONICAL_INPUT_MISMATCH` üretir. Prompt template ref ve
digest'i seçili istemci becerisinin ref ve digest'ine eşittir. Prompt envelope, ortak kökteki prompt
kaydından üretilen metadata projeksiyonuyla doğrulanan aynı project/client/session/turn/event'e ait
`allow`/`clean`
`PromptIngressReceipt` kaydına birebir bağlıdır ve beklenen envelope bu değerlerden yeniden
kurulur; uyuşmazlık `PROMPT_BINDING_MISMATCH` üretir. `PASS` yolunda context, retrieval ve
tool-result manifestlerinin her biri yalnız `availability: not-used`, `reason_code: NOT_USED`,
`item_count: 0` ve kendi canonicalization değeriyle kurulan kanonik boş yükün
(`{canonicalization, items: []}`) digest'ini taşır. `available` manifest ile null digest'li
`unavailable` manifest dahil başka her biçim `AUDIT_MANIFEST_UNVERIFIABLE` ile reddedilir;
supplemental girdi kullanılan veya kullanımı gözlenemeyen koşum `BLOCKED_INCOMPLETE` kalır.

Primary evaluation `finalize-review`'un policy uygulamasını ayrı invocation/span ve zaman
aralığıyla verdict, reason codes, şablon gerekçesi ve skorlarla taşır. İkinci geçiş kaydı commit
kancasının aynı raporlardan bağımsız policy yeniden hesabıdır: farklı invocation/span, validator
identity/version/digest ve checked-digest-set digest'i taşır; `recalculated` alanı kancanın hesapladığı
karar, reason code ve skorlardır. İki hesap uyuşmazsa `finalize-review` hiçbir kayıt yazmaz ve
`POLICY_RECALCULATION_MISMATCH` döndürür; commit kancası yayımlanmış receipt'in beyanını da
raporlardan yeniden hesaplayarak doğrular. Bu kayıt harici validator bağımsızlığı veya
deterministik runtime kanıtı değildir. Mismatch, eksik zorunlu binding veya stale digest
`BLOCKED_INCOMPLETE` üretir.

`model_rerun` ayrı ve best-effort capability'dir; exact output garantisi daima `false`'tur. Genel
receipt/audit ham prompt, kaynak içeriği, PII, secret veya credential taşımaz. Tam içerik gelecekte
zorunlu olursa yalnız erişim kontrollü ve süreli bir `evidence-vault:` referansı tutulabilir;
içeriğin kendisi genel audit'e gömülmez. Decision evidence digest'i decision'a; decision digest'i
receipt'e; kendi hash alanı hariç canonical receipt digest'i ilk audit olayına; her audit olayı da
bir önceki event digest'ine bağlanır. Zincir ortak kökte bir kez yazılan kayıttır; imza/WORM kanıtı
değildir. Kendi alanı hariç bütün iç ve kurulan nesne özetlerini komutlar hesaplar; ajanın
`work/` altındaki uzman değerlendirmeleri kanıt değildir ve commit kancası onları okumaz.
Aktif `kt-agentic-review-reuse-json-v3` kimliğini `finalize-review` exact top-level/nested nesnenin
tamamından, özellikle on iki complete `agent_results` nesnesinden hesaplar; seçilmiş alan özeti veya
`{agent_id,status,report_sha256}` indirgemesi geçerli değildir. Başka reuse kimliği taşıyan receipt
reuse yetkisi vermez.

Native session kimliği ham olarak genel receipt'e yazılmaz. `/governed-review` submission'ının
prompt bağını yalnız `review-start` canonical `current-prompt-metadata --client-id <client>`
kuralıyla seçer; genel shell listesi/okuması, caller-selected path, ham kaynak makbuz, HOME veya
transcript taraması kullanılmaz. Kayıt yoksa, okunamıyorsa veya seçim belirsizse
`BLOCKED_INCOMPLETE` kalır; makbuz uydurulmaz. Koşum, prompt-ingress kancasının aynı
project/client'a ait tekil güncel `PromptIngressReceipt` kaydındaki `prompt_session_id` değerini
taşır. Client envelope session alanı sağlıyorsa canonical binding
`session:client.<sha256(raw-native-session-utf8)>` biçimindedir; ham session veya transcript
içeriği okunmaz, kopyalanmaz ya da saklanmaz. Claude/Codex command eventindeki `session_id` ve
Cursor eventindeki `conversation_id` aynı privacy-safe digest'e yeniden hesaplanıp receipt ile
eşleşmelidir. Eksik, ambiguous veya uyuşmayan zorunlu session binding
`BLOCKED_INCOMPLETE` üretir. VS Code eventinde session opsiyoneldir; alan yoksa receipt session'ı
native event tarafından doğrulanmış sayılmaz ve daha güçlü claim kurulmaz.
Client version kaynağı receipt'te typed olmalıdır: yalnız Cursor `cursor_version` eşleşmesi
`native-event-observed`; Claude, Codex ve VS Code/Copilot sürümleri
`agent-self-observed` metadata'dır. Eventte bulunmayan sürüm için native pin-match iddiası kurulmaz;
değer gerçekten gözlenemiyorsa `unavailable` kaydı PASS/reuse yerine `BLOCKED_INCOMPLETE` bırakır.

Artifact yayın sırası değişmezdir: `review-start` snapshot'ı, koşum bağlamını ve bağlama
girdilerini yazar; gerekli profil observation'ları tamamlanır. Sonra tek ayrı komut olarak
`python3 .kt-scaffold/hooks/governance_client.py finalize-review --run-id <run_id>` çalıştırılır.
Finalizer policy'yi uygular, ikinci geçişi hesaplar, decision evidence'ı kurar, `decision.json`'ı ve
karar `PASS` ise run-scoped `receipt.json`'ı yazar; koşumu commit kancasının bütün denetimlerinden
geçirir, receipt'e bağlı 14 olaylık audit dizisini koşum dizinine bir kez yazar ve ancak sonra
koşumu staged snapshot için yayımlar. `PASS` dışı kararda yalnız karar yazılır; receipt, audit ve
yayın oluşmaz. Agent karar, receipt, audit JSON'u veya yayın işaretini elle kurmaz; bu dosyalar ajan
dosya araçlarına kapalıdır. Hash yönü `decision-evidence -> decision -> receipt -> audit` biçiminde
tek yönlüdür; receipt audit path/count metadata'sını taşıyabilir ancak audit digest'ini geriye
bağlayıp döngü kurmaz. Aşamaların zamanları ilgili anda komutun gerçekten gözlediği UTC saatten
gelir. Sentetik, sabit, gelecek zamanlı veya kronolojiyle çelişen timestamp kullanılamaz; saat
gözlenemiyorsa sonuç `BLOCKED_INCOMPLETE` kalır.

Finalizer, bağlı raporların ve receipt'in yayın zamanlarını gözlenebilir başlangıç/tamamlanma sınırı
olarak kullanır: `review_started` ve `agent_completed` olayları rapor dosyalarının,
`review_completed` olayı receipt dosyasının yayın zamanıdır. Audit zamanlarını ajan yazmaz ve
finalizer bunları model içi çağrı telemetry'si diye sunmaz. İlk on üç olay primary başlangıcından
geç, son olay receipt oluşturulmasından erken olamaz.
`decision.evaluation_started_at` primary evaluation `started_at` değerine, `decision.decided_at`
ikinci geçişin `completed_at` değerine eşittir; primary başlangıcı <= primary tamamlanması <=
ikinci geçiş tamamlanması olmalıdır, aksi `TIMESTAMP_ORDER_INVALID` üretir. Audit'te 0. konum
`review_started`, 1-12. konumlar katalog sırasıyla değil gözlenen tamamlanma sırasıyla
`agent_completed`, 13. konum `PASS` decision digest'i ve decision `span_id` değerine bağlı
`review_completed` olayıdır; receipt içindeki `agent_results` katalog sırasını korur.
Her `agent_completed` olayı Agent sonucuyla exact `agent_id`, `invocation_id`, `span_id`,
`status` ve `report_sha256` üzerinden eşleşir; on iki kimlik tekil olmalıdır. Tekrarlı, bilinmeyen
veya yanlış invocation'a bağlı olay `AUDIT_AGENT_MISMATCH` ile reddedilir. `observed_at`
değerleri bu yayın zamanlarından üretilir; olay zamanları azalmayan sırada olmalıdır. Audit
yazıldıktan sonra değiştirilmez. Aynı audit ile retry mevcut kaydı yeniden kullanır
ve yeni kayıt üretmez; farklı audit reddedilir. Finalizer koşumu önce commit kancasının bütün
denetimlerinden geçirir; kancanın reddedeceği koşum için audit yazmaz, yayımlamaz ve kancanın reason
code'unu döndürür. Ajan bu durumda uzman raporlarına dokunmaz; `SNAPSHOT_CHANGED` ve
`REPORT_BINDING_MISMATCH` yeni koşum ister, diğer kodlar tanıyla raporlanır. Yazım veya yayın
kesintisinde aynı run için finalizer yeniden çağrılır; yazılmış karar ve receipt yeniden kullanılır,
yeni uzman, test veya kullanıcı onayı istenmez. Finalizer p95 <=10 saniye
bir ölçüm hedefidir, bu kural tek başına sağlandığına dair canlı performans kanıtı değildir.

Desteklenen client-native yüzeylerde `protocol:mandatory-governed-execution-phase1` bir prompt
önerisi değil harness protokolüdür: exact snapshot, on iki ayrı Agent observation, bağlı Agentic
evaluator, decision, snapshot receipt, review audit zinciri ve audit sonrası koşum yayını
uygun commit eyleminden önce eksiksiz olmalıdır. Aggregation/evaluator policy, bu kural,
selected-client skill ve her Agent paketi sürüm+
digest ile receipt'e bağlanır. Prompt template/envelope, context/retrieval/tool-result manifestleri,
ikinci-geçiş validator sonucu ve decision/receipt/audit digest zinciri de aynı mandatory kaydın
parçasıdır. Eksik, stale, tahrif edilmiş veya uyuşmayan zincir
`BLOCKED_INCOMPLETE` üretir. Harness kendi `sha256` alanı hariç tam Mandatory Governed Execution
nesnesinin sorted/minified UTF-8 ve tek LF sonlu SHA-256 değerini taşır. Bununla birlikte harici
terminal, Git GUI, opaque wrapper ve client hook disable/trust/bypassını mutlak önleme Faz 1 iddiası
değildir; yönetilen Git/runtime/CI admission Faz 2 kapsamıdır.

Governance digest kapsamı Faz 1 evidence ve prompt/olay şemalarını, local-state policy'yi,
evaluator policy schema/YAML'ını, aggregation instructions'ı ve client-neutral receipt guard,
prompt/lifecycle hook, yönetişim istemcisi, ortak kayıt yazıcısı ve governed-review skill
byte'larını içerir. Verifier project manifest artifact kataloğu ile bu managed
asset'lerin güncel byte digest'lerinden governance digest'i yeniden hesaplar; aynı `$id` korunarak
gevşetilmiş schema veya managed manifestte yeniden hash'lenmiş projection/skill yine deny olur.
`.kt-scaffold/manifest.json`, project manifest ve hook byte'ları yerel mutable trust root olarak
kalır; bu kontrol imzalı/uzak/immutable authority attestation iddiası değildir.

Second-pass validator `version` alanı doğrulanmış evaluator policy version'ına; `sha256` alanı
`kt-agentic-second-pass-validator-binding-json-v1` ile doğrulanmış evaluator policy, selected skill
ve harness digest'lerine bağlanır. Guard ayrı invocation/span'i, declared recalculation eşitliğini ve
toplama politikasının raporlardan yeniden hesaplanan sonucunu denetler; bulguları yorumlamaz ve
host-observed harici bir invocation kanıtlamaz; bu nedenle `external_independence_proven` daima
false kalır. Binding unavailable/mismatch ise PASS
reuse verilmez.

Dört istemci projeksiyonu kanıt üretmeyen ve bulguları yorumlamayan aynı repo-local, Python
standard-library-only receipt-integrity harness'ını kullanır; harness toplama politikasının
sonucunu yalnız doğrulamak için raporlardan yeniden hesaplar; kurulu/import
edilebilir `kt_scaffold`, PyYAML veya jsonschema gerektirmez, fakat hostta `python3` gerektirir.
Desteklenen `python-fastapi` proje profili zaten Python tabanlı proje araçlarını taşır; bu yine de
istemci hostunda interpreter activation/L2 kanıtı değildir. Cursor `beforeShellExecution` command
yüzeyinde `failClosed: true` ister. Claude, Codex ve VS Code/Copilot host error/timeout/trust/disable
sınırları aynı değildir; bu yüzden bütün istemciler yalnız `conditional-native-guard`, L1
projeksiyon iddiası taşır ve identical enforcement iddiası taşımaz. Native kanca dosyasının varlığı,
on iki Agent invocation'ı veya L1 test tek başına gerçek bloklama/L2 kanıtı değildir. Harici
terminal/Git UI ve opaque wrapper kapsam dışıdır; fail-open/bypass kalıntısı olan yüzey enforced veya
production-ready diye etiketlenmez.

Verifier yalnız hook yürütülmeden hemen önce gözlenen index snapshot'ını doğrular. Eşzamanlı index
değişimi veya sonradan çalışan Git/pre-commit hook'u için TOCTOU'yu mutlak önlediği iddia edilmez;
native L2 allow kanıtı oluşan commit tree'sini receipt snapshot'ıyla ayrıca karşılaştırmalı,
yönetilen Git/CI kapısı da daha güçlü admission için yeniden doğrulamalıdır.

Faz 1 etkin hook ve beceri yolu kurulu/import edilebilir `kt_scaffold`,
`commit_governance.py`, `review_baseline.py`, proje MCP'si veya Web aracı gerektirmez. Mekanik
commit kapısı başlatıcısı `.kt-scaffold/hooks/commit_governance_guard.py` kurulu `kt_scaffold`
runtime'ını açık `--git-hook`, `--bind-baseline` ve `--prepare-review` kiplerinde çağırır; varsayılan
pre-commit akışına ve native kancaya bağlı değildir. İçeriği hook event'inde görünmeyen keyfi
interpreter, dış wrapper, alias, harici terminal veya Git UI işlemi repo-local native kancayla
evrensel olarak önlenemez. CI/admission ise teslim iddiası için otoriter yeniden doğrulamadır.
Becerinin yazma yetkisi yalnız Git tarafından dışlanan review artifact
alanıyla sınırlıdır; uygulama/kod dosyasını değiştirme, AutoFix, deploy veya production admission
yetkisi vermez. Beceri paket kurmaz; `pip`, `npm`, sistem paket yöneticisi, user/global
site-packages veya proje dışındaki herhangi bir host durumu değiştirilmez. Harici validator
bulunmaması bağımlılık kurma yetkisi vermez; typed sözleşme güvenle doğrulanamıyorsa sonuç
`BLOCKED_INCOMPLETE` kalır. Exact Git index snapshot'ında değişmemiş kanonik Agent paketi ve
projection değerlendirmenin referansıdır, aday değildir: uzmanlar bunlar hakkında bulgu üretmez ve
bu yolları `scanned_files` listesine eklemez. `scanned_files` yalnız staged adaydan incelenen
repository-relative yolları taşır. Review artifact'larının ham prompt/kaynak içeriği taşımaması, istemcinin kendi
transcript/tool-result geçmişinin bunları tutmadığını kanıtlamaz. Review sırasında proje MCP/Web aracı
gözlenmemesi de istemcinin model/control-plane ağını izole ettiği anlamına gelmez.

Faz 2 için hedef tek kanonik deterministik policy+engine çekirdeğidir. Yerel yönetilen runtime bu
çekirdeği doğrudan çağırabilir; Streamable HTTP MCP aynı çekirdeğe yardımcı uzak transport sunabilir.
MCP ikinci karar otoritesi değildir. Her iki transport policy/engine digest'i, exact snapshot,
idempotency, aynı `decision_evidence.audit_replay` kaydı, şema-geçerli decision/receipt/audit ve
fail-closed harness sonucunu aynı sözleşmeyle mekanik olarak yeniden doğrulamalıdır. Bu hedef Faz 1
Agentic anlamsal karar otoritesini değiştirmez ve model rerun exactness iddiası kurmaz.

## Ortak kayıt sınırı

Kayıt yeri, session kimliği ve fallback yasağı `55-prompt-veri-guvenligi` kuralındadır. Snapshot,
observation, decision ve gate receipt karar çalışma yapıtlarıdır; ham LLM yanıtı veya log kopyası
değildir. Review koşumu repo dışındaki ortak yönetişim kökünde `<project_id>/governed-review/<run_id>/`
altındadır; receipt içindeki `report_directory`, `report_path`, `decision_path` ve `audit_path`
değerleri bu köke göreli `governed-review/<run_id>/...` yollarıdır. Native receipt guard
salt-okunurdur: staged snapshot için yayımlanmış en yeni koşumu bulur, receipt, rapor, karar ve
14 olaylık audit zincirini yerelde yeniden doğrular; dosya yazmaz ve native allow/deny, retry veya
hook hatası sonucunu kaydetmez. Ajanın dosya araçları ortak köke yalnız uzman değerlendirmelerini
(`work/<agent-slug>-evaluation.json`) yazabilir; koşum girdilerini `review-start`, raporları
`observation`, kararı ve receipt'i `finalize-review` yazar; kayıtlar, audit ve yayın işaretleri
kapalıdır. Bu bir ajan korkuluğudur: shell veya insan eliyle üretilmiş eksiksiz bir zincir yerelde
ayırt edilemez ve son deterministik denetim CI'dadır. `commit-governance` kaydının tek üreticisi,
`.kt-scaffold/hooks/commit_governance_guard.py` başlatıcısıyla açıkça çağrılan opt-in
`commit_governance` runtime'ıdır. Host hook hatası, LLM API hatası ve gözlenemeyen iç deneme ayrı
durumlardır; ham exception/model/tool/transcript içeriği kayıt değildir. Yayımlanmış koşumun receipt'i
düzeltilecekse yeni run oluştur.

Log konumu sorulduğunda bu sınırı açıkla. Prompt, LLM çağrı olayı, review ve commit kayıtları macOS'ta
`/Users/Shared/kt-scaffold/governance/`, Windows'ta `%ProgramData%\kt-scaffold\governance\`,
Linux'ta `/var/lib/kt-scaffold/governance/` altında `<project_id>/<tür>/` desenindedir. Ön kontrol
kökün yazılamadığını bildiriyorsa kayıt oluşmaz; yol uydurma ve logu repoya yazma.

Kullanıcı tek bir uzman Agent'ı çağırmak istediğinde (ör. "bilgi güvenliği ajanını çalıştır") onu
native Agent olarak ayrı çağır ve sonucu `agent-platform/agentic-agent-consultation.schema.json`
biçiminde, tek ayrı komutla `python3 .kt-scaffold/hooks/governance_client.py consultation`
komutunun standart girdisine ver; komut kaydı ortak kökte `agent-consultation` türünde bir kez yazar.
Kayıt güncel exact snapshot özetini, `invocation_id` ve bulguları taşır; `authority`
`advisory-consultation`, `commit_authority` `false`, `decision` `null` ve `protected_audit`
`not-recorded` olur. Danışma kaydını dosya aracıyla yazma; makbuz, karar ya da audit üretme; commit
kapısı onu kabul etmez. Sonucu kullanıcıya danışma bulgusu olarak bildir; commit için tam
`governed-review` gerekir.
