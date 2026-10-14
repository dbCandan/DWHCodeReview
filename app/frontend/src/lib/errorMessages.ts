import {ApiError} from '@/lib/apiClient';

/**
 * Plain Turkish text for every stable error code the backend returns. The screen never shows the
 * raw response text; an unknown code falls back to a message chosen by the HTTP status.
 */
const MESSAGES: Record<string, string> = {
  not_authenticated: 'Oturumunuz sona erdi. Lütfen yeniden giriş yapın.',
  session_expired: 'Oturumunuzun süresi doldu. Lütfen yeniden giriş yapın.',
  session_revoked: 'Oturumunuz kapatıldı. Lütfen yeniden giriş yapın.',
  forbidden: 'Bu işlem için yetkiniz yok.',
  origin_not_allowed: 'İstek uygulama adresinden gelmediği için reddedildi.',
  invalid_request: 'Gönderilen bilgiler geçersiz.',
  not_found: 'Kayıt bulunamadı.',
  tenant_unavailable: 'Hesabınızın bağlı olduğu kurum kaydı kullanılamıyor.',
  user_not_found: 'Kullanıcı bulunamadı.',
  super_admin_protected: 'Süper yönetici hesabının rolü ve durumu bu ekrandan değiştirilemez.',
  own_account: 'Kendi hesabınızın durumunu değiştiremezsiniz.',
  rule_set_draft_conflict: 'Kurallar başka biri tarafından değiştirildi; sayfayı yenileyin.',
  rule_id_invalid: 'Kural kimliği KuralNN biçiminde olmalıdır.',
  rule_id_duplicate: 'Aynı kural kimliği birden çok kurala verilemez.',
  rule_id_reused: 'Daha önce kullanılmış bir kural kimliği yeni kurala verilemez; sayfayı yenileyin.',
  rule_text_too_long: 'Kural metni en çok 8.000 karakter olabilir.',
  rule_set_too_large: 'Taslak en çok 200 kural içerebilir.',
  rule_set_empty: 'Hiç kural içermeyen taslak yayımlanamaz.',
  no_published_rule_set: 'Henüz yayımlanmış kural yok; inceleme başlatılamaz.',
  rule_set_version_not_found: 'Kural sürümü bulunamadı.',
  rule_group_name_invalid: 'Kural grubu adı 1-80 karakter olmalıdır.',
  rule_group_name_duplicate: 'Aynı adla iki kural grubu tanımlanamaz.',
  rule_group_too_many: 'Bir sürümde en çok 50 kural grubu olur.',
  rule_group_unknown_membership: 'Kural, taslakta tanımlı olmayan bir gruba atanamaz.',
  rule_group_unknown: 'Seçilen kural grubu yayımlanmış sürümde yok; sayfayı yenileyin.',
  rule_group_selection_empty: 'Seçilen kural gruplarında hiç kural yok.',
  rule_unknown: 'Seçilen kural yayımlanmış sürümde yok; sayfayı yenileyin.',
  rule_summary_invalid: 'Kural özeti tek satırda en çok 200 karakterlik bir cümle olmalıdır.',
  rule_text_invalid: 'Ayrıntılı kural metni boş olamaz.',
  publish_requires_approval: 'Taslak süper yönetici onayıyla yayımlanır; taslağı onaya gönderin.',
  proposal_forbidden: 'Kural önerme yetkiniz yok; süper yöneticiden yetki isteyin.',
  proposal_rules_empty: 'Grup önerisi en az bir kural içermelidir.',
  proposal_not_pending: 'Öneri artık beklemiyor; sayfayı yenileyin.',
  proposal_conflict: 'Öneri en son yayımlanmış sürüme artık uymuyor; reddedip yeniden önerilmesini isteyin.',
  rule_proposal_not_found: 'Kural önerisi bulunamadı.',
  rejection_reason_invalid: 'Ret gerekçesi 1-500 karakter olmalıdır.',
  publish_request_not_found: 'Yayın isteği bulunamadı.',
  publish_request_not_pending: 'Yayın isteği artık beklemiyor; sayfayı yenileyin.',
  publish_request_stale: 'Taslak istekten sonra değişti; kural yöneticisi yeniden onaya göndermelidir.',
  schedule_invalid: 'Ad, nesne seçimi veya periyot geçersiz.',
  recipient_invalid: 'Alıcı e-posta adreslerinden biri geçersiz veya alıcı yok.',
  recipient_domain_not_allowed: 'Alıcı yalnız kurum e-posta alan adlarından olabilir.',
  schedule_name_duplicate: 'Aynı adla ikinci bir zamanlanmış inceleme tanımlanamaz.',
  scheduled_review_not_found: 'Zamanlanmış inceleme bulunamadı.',
  scheduled_review_running: 'Bu tanımın bir koşumu sırada bekliyor veya sürüyor.',
  schedule_unavailable: 'Zamanlanmış inceleme tanımına veya sahibine ulaşılamadı.',
  setting_out_of_range: 'Aynı anda çalışacak zamanlanmış koşum sayısı 1-10 arasında olmalıdır.',
  sql_connection_not_configured: 'SQL Server bağlantısı yapılandırılmamış.',
  sql_connection_invalid: 'Sunucu veya kullanıcı adı geçersiz.',
  sql_setting_fixed: 'Bu ayar bu ortamda değiştirilemez.',
  sql_connection_conflict:
    'Bağlantı ayarı aynı anda başka biri tarafından kaydedildi; sayfayı yenileyip yeniden deneyin.',
  sql_server_unreachable: "SQL Server'a ulaşılamadı.",
  sql_login_failed: 'SQL Server girişi reddedildi.',
  sql_timeout: 'SQL Server zamanında yanıt vermedi.',
  sql_tls_failed: 'SQL Server ile güvenli bağlantı kurulamadı.',
  sql_query_failed: 'SQL Server sorgusu tamamlanamadı.',
  password_required: 'Bağlantıyı test etmek için parolayı girin.',
  database_not_allowed: 'Sistem veritabanları incelenemez.',
  object_not_found: 'Tanım alınamadı (nesne yok veya yetki yok).',
  selection_empty: 'İnceleme için en az bir nesne seçin.',
  object_type_invalid: 'Seçilen nesne türü incelenemiyor.',
  sql_text_empty: 'SQL metni boş olamaz.',
  sql_text_too_long: 'SQL metni en çok 120.000 karakter olabilir.',
  label_too_long: 'Etiket en çok 200 karakter olabilir.',
  rate_limited: 'Çok fazla inceleme başlattınız; biraz sonra yeniden deneyin.',
  llm_not_configured: 'LLM bağlantısı yapılandırılmamış.',
  llm_url_invalid: 'LLM adresi geçersiz: kullanıcı bilgisi veya parça içermeyen bir http(s) adresi girin.',
  network_policy_denied: 'LLM adresi kurum içi ağda değil; bu adrese istek gönderilemez.',
  llm_call_not_found: 'LLM çağrı özeti bulunamadı.',
  review_failed: 'İnceleme tamamlanamadı.',
  review_interrupted: 'İnceleme yarıda kesildi.',
  review_run_not_found: 'İnceleme bulunamadı.',
  review_run_not_owner: 'Yalnız incelemeyi başlatan kişi bu işlemi yapabilir.',
  review_scope_forbidden: 'Tüm incelemeleri yalnız kural yöneticisi görebilir.',
  review_run_in_progress: 'Süren bir inceleme silinemez.',
  review_finding_not_found: 'Bulgu bulunamadı.',
  review_rule_result_not_found: 'Kural sonucu bulunamadı.',
  false_positive_not_applicable: 'Yalnız bulgusu olmayan başarısız kural sonucu işaretlenebilir.',
  sql_text_unavailable: 'Bu inceleme için saklanmış SQL metni yok.',
};

const NETWORK_MESSAGE = 'Sunucuya ulaşılamadı. Bağlantınızı denetleyip yeniden deneyin.';
const GENERIC_MESSAGE = 'Beklenmeyen bir hata oluştu. Biraz sonra yeniden deneyin.';

function messageForStatus(status: number): string {
  if (status === 401) return MESSAGES.not_authenticated;
  if (status === 403) return MESSAGES.forbidden;
  if (status === 404) return MESSAGES.not_found;
  if (status === 413) return 'Seçim, sunucunun tek istekte kabul ettiği boyutu aşıyor; daha az nesne seçip yeniden deneyin.';
  if (status === 409) return 'İşlem güncel durumla çakıştı; sayfayı yenileyip yeniden deneyin.';
  if (status === 400 || status === 422) return MESSAGES.invalid_request;
  if (status === 429) return 'Çok fazla istek gönderildi; biraz sonra yeniden deneyin.';
  if (status === 504) return 'Sunucu zamanında yanıt vermedi; biraz sonra yeniden deneyin.';
  if (status >= 500) return 'Sunucu şu anda yanıt veremiyor; biraz sonra yeniden deneyin.';
  return GENERIC_MESSAGE;
}

/** Message for a stable code, when the screen knows it. */
export function messageForCode(code: string | null | undefined): string | undefined {
  return code ? MESSAGES[code] : undefined;
}

/** Person-facing text for any failure of a service call. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return messageForCode(error.code) ?? messageForStatus(error.status);
  if (error instanceof TypeError) return NETWORK_MESSAGE;
  return GENERIC_MESSAGE;
}

/** The stable code of a failed service call, if it carried one. */
export function errorCode(error: unknown): string | undefined {
  return error instanceof ApiError ? error.code : undefined;
}
