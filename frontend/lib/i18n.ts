// UI string dictionary covering Deskwise's supported languages with English
// fallback. Selecting a language persists on the user profile and sets the AI
// reply language.
import type { UiLanguage } from './api'

type Entry = Record<'en', string> & Partial<Record<UiLanguage, string>>

const STRINGS: Record<string, Entry> = {
  // workspace sidebar / nav
  overview: { en: 'Overview', es: 'Resumen', fr: 'Aperçu', de: 'Übersicht', ar: 'نظرة عامة', pt: 'Visão geral', ur: 'Khulasa' },
  askAi: { en: 'Ask AI', es: 'Preguntar a la IA', fr: 'Demander à l’IA', de: 'KI fragen', ar: 'اسأل الذكاء الاصطناعي', pt: 'Perguntar à IA', ur: 'AI se poochein' },
  teamChat: { en: 'Team Chat', es: 'Chat de equipo', fr: 'Chat d’équipe', de: 'Team-Chat', ar: 'دردشة الفريق', pt: 'Chat da equipa', ur: 'Team Chat' },
  documents: { en: 'Documents', es: 'Documentos', fr: 'Documents', de: 'Dokumente', ar: 'المستندات', pt: 'Documentos', ur: 'Documents' },
  shared: { en: 'Shared with me', es: 'Compartido conmigo', fr: 'Partagés avec moi', de: 'Mit mir geteilt', ar: 'تمت مشاركتها معي', pt: 'Partilhado comigo', ur: 'Mere sath share' },
  attendance: { en: 'Attendance', es: 'Asistencia', fr: 'Présence', de: 'Anwesenheit', ar: 'الحضور', pt: 'Presença', ur: 'Haziri' },
  members: { en: 'Members', es: 'Miembros', fr: 'Membres', de: 'Mitglieder', ar: 'الأعضاء', pt: 'Membros', ur: 'Members' },
  audit: { en: 'Audit log', es: 'Registro de auditoría', fr: 'Journal d’audit', de: 'Prüfprotokoll', ar: 'سجل التدقيق', pt: 'Registo de auditoria', ur: 'Audit record' },
  usagePlan: { en: 'Usage & plan', es: 'Uso y plan', fr: 'Utilisation et forfait', de: 'Nutzung & Tarif', ar: 'الاستخدام والخطة', pt: 'Uso e plano', ur: 'Istemaal aur plan' },
  settings: { en: 'AI settings', es: 'Ajustes de IA', fr: 'Paramètres IA', de: 'KI-Einstellungen', ar: 'إعدادات الذكاء الاصطناعي', pt: 'Definições de IA', ur: 'AI settings' },
  backToLanding: { en: '← Back to landing', es: '← Volver al inicio', fr: '← Retour à l’accueil', de: '← Zur Startseite', ar: '← العودة للرئيسية', pt: '← Voltar ao início', ur: '← Wapis home' },
  logout: { en: 'Log out', es: 'Cerrar sesión', fr: 'Déconnexion', de: 'Abmelden', ar: 'تسجيل الخروج', pt: 'Terminar sessão', ur: 'Log out' },
  // chat
  askPlaceholder: {
    en: 'Ask anything about your documents…',
    es: 'Pregunta lo que quieras sobre tus documentos…',
    fr: 'Posez une question sur vos documents…',
    de: 'Fragen Sie etwas zu Ihren Dokumenten…',
    ar: 'اسأل أي شيء عن مستنداتك…',
    pt: 'Pergunte o que quiser sobre os seus documentos…',
    ur: 'Documents ke bare mein kuch bhi poochein…',
  },
  stop: { en: 'Stop', es: 'Detener', fr: 'Arrêter', de: 'Stopp', ar: 'إيقاف', pt: 'Parar', ur: 'Rukein' },
  newChat: { en: 'New chat', es: 'Nuevo chat', fr: 'Nouvelle discussion', de: 'Neuer Chat', ar: 'محادثة جديدة', pt: 'Novo chat', ur: 'Nayi chat' },
  history: { en: 'History', es: 'Historial', fr: 'Historique', de: 'Verlauf', ar: 'السجل', pt: 'Histórico', ur: 'Purani batein' },
  sources: { en: 'Sources', es: 'Fuentes', fr: 'Sources', de: 'Quellen', ar: 'المصادر', pt: 'Fontes', ur: 'Zariye' },
  helpful: { en: 'Helpful', es: 'Útil', fr: 'Utile', de: 'Hilfreich', ar: 'مفيد', pt: 'Útil', ur: 'Acha laga' },
  notHelpful: { en: 'Not helpful', es: 'Poco útil', fr: 'Inutile', de: 'Nicht hilfreich', ar: 'غير مفيد', pt: 'Não útil', ur: 'Acha nahi laga' },
  // documents
  uploadDocument: { en: 'Upload document', es: 'Subir documento', fr: 'Importer un document', de: 'Dokument hochladen', ar: 'رفع مستند', pt: 'Carregar documento', ur: 'Document upload karein' },
  download: { en: 'Download', es: 'Descargar', fr: 'Télécharger', de: 'Herunterladen', ar: 'تنزيل', pt: 'Transferir', ur: 'Download' },
  preview: { en: 'Preview', es: 'Vista previa', fr: 'Aperçu', de: 'Vorschau', ar: 'معاينة', pt: 'Pré-visualizar', ur: 'Dekhein' },
  share: { en: 'Share', es: 'Compartir', fr: 'Partager', de: 'Teilen', ar: 'مشاركة', pt: 'Partilhar', ur: 'Share' },
  delete: { en: 'Delete', es: 'Eliminar', fr: 'Supprimer', de: 'Löschen', ar: 'حذف', pt: 'Eliminar', ur: 'Delete' },
  searchDocs: {
    en: 'Search your permitted documents…',
    es: 'Buscar en tus documentos permitidos…',
    fr: 'Rechercher dans vos documents autorisés…',
    de: 'Zugängliche Dokumente durchsuchen…',
    ar: 'ابحث في مستنداتك المصرح بها…',
    pt: 'Pesquisar nos seus documentos autorizados…',
    ur: 'Apne documents talash karein…',
  },
  indexing: { en: 'Indexing…', es: 'Indexando…', fr: 'Indexation…', de: 'Indizierung…', ar: 'جارٍ الفهرسة…', pt: 'A indexar…', ur: 'Index ho raha hai…' },
  indexFailed: { en: 'Index failed — retry', es: 'Error al indexar — reintentar', fr: 'Échec — réessayer', de: 'Fehler — erneut versuchen', ar: 'فشلت الفهرسة — إعادة المحاولة', pt: 'Falha — tentar novamente', ur: 'Index fail — dobara karein' },
  allCategories: { en: 'All categories', es: 'Todas las categorías', fr: 'Toutes les catégories', de: 'Alle Kategorien', ar: 'كل الفئات', pt: 'Todas as categorias', ur: 'Tamam categories' },
  // common
  loading: { en: 'Loading…', es: 'Cargando…', fr: 'Chargement…', de: 'Laden…', ar: 'جارٍ التحميل…', pt: 'A carregar…', ur: 'Load ho raha hai…' },
  save: { en: 'Save', es: 'Guardar', fr: 'Enregistrer', de: 'Speichern', ar: 'حفظ', pt: 'Guardar', ur: 'Mehfooz karein' },
  cancel: { en: 'Cancel', es: 'Cancelar', fr: 'Annuler', de: 'Abbrechen', ar: 'إلغاء', pt: 'Cancelar', ur: ' Mansookh' },
  language: { en: 'Language', es: 'Idioma', fr: 'Langue', de: 'Sprache', ar: 'اللغة', pt: 'Idioma', ur: 'Zuban' },
  // attendance
  markedPresent: { en: 'You are marked present for today.', es: 'Asistencia registrada para hoy.', fr: 'Présence enregistrée pour aujourd’hui.', de: 'Sie sind für heute als anwesend markiert.', ar: 'تم تسجيل حضورك لهذا اليوم.', pt: 'Presença registada para hoje.', ur: 'Aaj ki haziri ho gayi.' },
  markPresent: { en: "I'm at the office — mark me present", es: 'Estoy en la oficina — registrar asistencia', fr: 'Je suis au bureau — pointer ma présence', de: 'Ich bin im Büro — Anwesenheit erfassen', ar: 'أنا في المكتب — سجّل حضوري', pt: 'Estou no escritório — marcar presença', ur: 'Main daftar mein hoon — haziri lagayein' },
  // overview
  welcomeBack: { en: 'Welcome back,', es: 'Bienvenido de nuevo,', fr: 'Bon retour,', de: 'Willkommen zurück,', ar: 'مرحبًا بعودتك،', pt: 'Bem-vindo de volta,', ur: 'Khush amdeed,' },
  announcements: { en: 'Announcements', es: 'Anuncios', fr: 'Annonces', de: 'Ankündigungen', ar: 'الإعلانات', pt: 'Anúncios', ur: 'Elaan' },
  noAnnouncements: { en: 'No announcements yet.', es: 'Aún no hay anuncios.', fr: 'Aucune annonce pour le moment.', de: 'Noch keine Ankündigungen.', ar: 'لا توجد إعلانات بعد.', pt: 'Sem anúncios ainda.', ur: 'Koi elaan nahi.' },
}

export type StringKey =
  | 'overview'
  | 'askAi'
  | 'teamChat'
  | 'documents'
  | 'shared'
  | 'attendance'
  | 'members'
  | 'audit'
  | 'usagePlan'
  | 'settings'
  | 'backToLanding'
  | 'logout'
  | 'askPlaceholder'
  | 'stop'
  | 'newChat'
  | 'history'
  | 'sources'
  | 'helpful'
  | 'notHelpful'
  | 'uploadDocument'
  | 'download'
  | 'preview'
  | 'share'
  | 'delete'
  | 'searchDocs'
  | 'indexing'
  | 'indexFailed'
  | 'allCategories'
  | 'loading'
  | 'save'
  | 'cancel'
  | 'language'
  | 'markedPresent'
  | 'markPresent'
  | 'welcomeBack'
  | 'announcements'
  | 'noAnnouncements'

// Translate a key. Falls back to English, then to the key itself.
export function t(key: StringKey, lang: UiLanguage = 'en'): string {
  const entry = STRINGS[key]
  if (!entry) return key
  return entry[lang] ?? entry.en
}

export function makeT(lang: UiLanguage) {
  return (key: StringKey) => t(key, lang)
}
