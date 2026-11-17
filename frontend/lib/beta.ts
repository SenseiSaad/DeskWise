import type { ChatMode } from './api'

// Beta lockdown. During the beta only one chat provider is enabled; the others
// stay visible in the picker but are disabled, so the roadmap is discoverable
// without being selectable. Set NEXT_PUBLIC_BETA_PROVIDER=off to re-enable
// every provider (the buyer can flip this after the beta).
const raw = (process.env.NEXT_PUBLIC_BETA_PROVIDER ?? 'gemini').trim().toLowerCase()

export const BETA_LOCKED_MODE: ChatMode | null = raw === 'off' ? null : (raw as ChatMode)

export const BETA_NOTICE =
  'Beta: only Google Gemini is enabled right now. Local (Ollama), AWS Bedrock and Self-Hosted models are temporarily disabled while we finish testing.'

// Shown against the Bedrock option while it is locked. Bedrock runs on the
// account owner's own AWS Bedrock account, so usage bills to whoever owns the
// deployment — not to the end customer.
export const BEDROCK_DISABLED_NOTE =
  'Runs on your own AWS Bedrock account (billed to the account owner) for the best answer quality and fastest responses over your documents. Disabled during the beta.'

export const LOCAL_DISABLED_NOTE =
  'Runs a model on the server itself (Ollama). Disabled during the beta.'

export const SELFHOSTED_DISABLED_NOTE =
  'Runs against your own self-hosted inference server. Disabled during the beta.'

// Data-usage disclosure. Free-tier Gemini content may be used by Google to
// improve its products; paid-tier content is not. Operators must verify the
// current terms before uploading confidential material.
export const GEMINI_DATA_NOTICE =
  "Gemini data use: on Google's free tier, Google may use your prompts and uploaded document content to improve its products, and human reviewers may see it. On the paid tier, Google does not use it for improvement. Confirm Google's current Gemini API terms yourself before uploading confidential material."
