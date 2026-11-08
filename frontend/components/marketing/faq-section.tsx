'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { ChevronDown } from 'lucide-react'

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
                    className="group flex w-full items-start justify-between gap-4 text-left text-lg font-medium transition-colors hover:text-accent"
                  >
                    <span>{f.q}</span>
                    <motion.span
                      animate={{ rotate: isOpen ? 180 : 0 }}
                      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                      className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border border-border text-muted-foreground transition-colors group-hover:border-accent group-hover:text-accent"
                    >
                      <ChevronDown className="size-4" aria-hidden />
                    </motion.span>
                  </button>
                  <AnimatePresence initial={false}>
                    {isOpen && (
                      <motion.div
                        id={`faq-${i}`}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                        className="overflow-hidden"
                      >
                        <p className="pb-1 pt-3 pr-10 text-base leading-relaxed text-muted-foreground">
                          {f.a}
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>
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
