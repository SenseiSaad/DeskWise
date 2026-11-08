'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Minus, Plus } from 'lucide-react'

const FAQS = [
  {
    q: 'Do I or my team need technical skills to use Deskwise?',
    a: 'Not at all. If you know how to send a chat message, you can use Deskwise. Simply ask your questions in everyday English or Roman Urdu, or ask for a form to be filled, and Deskwise does the work.',
  },
  {
    q: 'Will our company files ever leak or be used to train public AI models?',
    a: 'Never. Your documents are stored in an encrypted, isolated private company vault. Your data is strictly yours and is never used to train public AI models.',
  },
  {
    q: 'Can employees see confidential files outside their department?',
    a: 'No. Access controls run before any search takes place. If an employee belongs to Marketing, they cannot see or ask the AI about private Finance or HR documents unless an administrator grants explicit access.',
  },
  {
    q: 'What file formats can we upload?',
    a: 'Deskwise supports PDFs, Microsoft Word (.docx), Excel spreadsheets (.csv), PowerPoint (.pptx), text documents, and scanned images with text.',
  },
  {
    q: 'How do the generated leave forms and official letters work?',
    a: 'When you request a leave form or HR letter, Deskwise fills in your profile information, reason, and company format automatically. You can copy it with one click or download it as a ready-to-sign Word (DOCX) or PDF file.',
  },
  {
    q: 'What payment methods do you support?',
    a: 'We support all international and local credit and debit cards (Visa, Mastercard) via Stripe secure checkout, as well as direct bank transfers and local mobile payments.',
  },
]

export function FaqSection() {
  const [open, setOpen] = useState<number | null>(0)

  return (
    <section className="py-20 sm:py-24 lg:py-28" aria-labelledby="faq-heading">
      <div className="container-page">
        <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <p className="eyebrow">Frequently Asked Questions</p>
            <h2 id="faq-heading" className="display-lg mt-5">
              Everything you
              <br />
              <span className="serif text-accent">need to know.</span>
            </h2>
            <p className="mt-5 max-w-sm text-sm leading-relaxed text-muted-foreground">
              Have another question not answered here? Our team is always ready to assist you.
            </p>
            <div className="mt-7">
              <a
                href="mailto:hello@openvault.site?subject=Deskwise%20Question"
                className="link-arrow"
              >
                Send us an email <ArrowRight className="size-3.5" aria-hidden />
              </a>
            </div>
          </div>

          <div className="divide-y divide-border border-y border-border">
            {FAQS.map((faq, index) => {
              const isOpen = open === index
              return (
                <div key={faq.q} className="py-6 sm:py-7">
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : index)}
                    aria-expanded={isOpen}
                    className="flex w-full items-start justify-between gap-4 text-left font-display text-[16px] font-medium tracking-tight text-foreground sm:text-[17px]"
                  >
                    <span>{faq.q}</span>
                    <span className="grid size-6 shrink-0 place-items-center rounded-full border border-border text-muted-foreground">
                      {isOpen ? <Minus className="size-3.5" /> : <Plus className="size-3.5" />}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="mt-4 pr-10 text-sm leading-relaxed text-muted-foreground animate-fade-in">
                      {faq.a}
                    </div>
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
