'use client'

import { useState } from 'react'
import { Minus, Plus } from 'lucide-react'

const FAQS = [
  {
    q: 'Do I need technical skills to use Deskwise?',
    a: 'No. If you can send a chat message, you can use Deskwise. Ask in everyday English or Roman Urdu and it does the rest.',
  },
  {
    q: 'Will our files leak or train public AI models?',
    a: 'No. Your documents live in a private space that only your company can reach, and they are never used to train public AI models.',
  },
  {
    q: 'Can employees see files outside their department?',
    a: 'No. Access is checked before every search. Someone in Marketing cannot see or ask about HR or Finance files unless an admin gives them access.',
  },
  {
    q: 'What files can I upload?',
    a: 'PDF, Word, Excel/CSV, PowerPoint, plain text, and scanned pages with text.',
  },
  {
    q: 'How do the forms and letters work?',
    a: 'Ask for a leave request or an HR letter. Deskwise fills in your details and the company format, then you copy it or download it as Word or PDF.',
  },
  {
    q: 'How do I pay?',
    a: 'By card (Visa or Mastercard) through secure checkout. Bank transfer is available on request.',
  },
]

export function FaqSection() {
  const [open, setOpen] = useState<number | null>(0)
  return (
    <section id="faq" className="scroll-mt-20 border-y border-border bg-surface py-20 sm:py-28" aria-labelledby="faq-heading">
      <div className="container-page">
        <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <p className="eyebrow">Questions</p>
            <h2 id="faq-heading" className="display-lg mt-5">
              Good to <span className="serif text-accent">know.</span>
            </h2>
            <p className="mt-5 max-w-sm text-base leading-relaxed text-muted-foreground">
              Something else? Email{' '}
              <a className="font-medium text-accent underline underline-offset-4" href="mailto:hello@openvault.site?subject=Deskwise%20question">
                hello@openvault.site
              </a>
              .
            </p>
          </div>
          <div className="divide-y divide-border border-y border-border">
            {FAQS.map((f, i) => {
              const isOpen = open === i
              return (
                <div key={f.q} className="py-5">
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : i)}
                    aria-expanded={isOpen}
                    aria-controls={`faq-${i}`}
                    className="flex w-full items-start justify-between gap-4 text-left text-lg font-medium"
                  >
                    <span>{f.q}</span>
                    <span className="mt-1 grid size-6 shrink-0 place-items-center rounded-full border border-border text-muted-foreground">
                      {isOpen ? <Minus className="size-3.5" aria-hidden /> : <Plus className="size-3.5" aria-hidden />}
                    </span>
                  </button>
                  {isOpen && (
                    <p id={`faq-${i}`} className="mt-3 pr-10 text-base leading-relaxed text-muted-foreground">
                      {f.a}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

export default FaqSection
