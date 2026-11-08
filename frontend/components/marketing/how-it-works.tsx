import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { Reveal } from '@/components/reveal'

const STEPS = [
  {
    title: 'Create your account',
    body: 'Sign up in 30 seconds. Your company gets a dedicated, private space with zero setup hassle.',
  },
  {
    title: 'Upload your documents',
    body: 'Drag and drop your company policies, employee handbooks, contracts, and standard operating procedures.',
  },
  {
    title: 'Choose who sees what',
    body: 'Keep sensitive HR or finance files protected. Team members only search what is relevant to their department.',
  },
  {
    title: 'Ask questions & generate forms',
    body: 'Your team gets instant answers with exact page citations, and generates official leave requests and letters with one click.',
  },
]

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="relative scroll-mt-24 overflow-hidden bg-[#151412] py-20 text-[#f3efe5] sm:py-24 lg:py-28"
      aria-labelledby="how-heading"
    >
      <div aria-hidden className="dot-grid pointer-events-none absolute inset-0 opacity-[0.12]" />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 top-1/3 size-[30rem] rounded-full bg-[radial-gradient(circle,rgba(217,167,95,0.16),transparent_65%)] blur-3xl"
      />

      <div className="container-page relative">
        <Reveal>
          <div className="flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="eyebrow text-[#d9a75f]">Easy 4-Step Process</p>
              <h2 id="how-heading" className="display-lg mt-5">
                Up and running in
                <br />
                <span className="serif text-[#d9a75f]">under five minutes.</span>
              </h2>
            </div>
            <p className="max-w-sm text-sm leading-relaxed text-[#f3efe5]/50 lg:pb-1">
              Upload your existing documents and start asking questions immediately.
              No complex migrations, no coding, and no special software to install.
            </p>
          </div>
        </Reveal>

        <div className="mt-14 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <Reveal key={step.title} delay={index * 80}>
              <article className="relative border-t border-white/15 pt-6">
                <span className="absolute -top-1 left-0 size-2 rounded-full bg-[#d9a75f]" aria-hidden />
                <p className="font-mono text-[11px] tracking-[0.12em] text-[#d9a75f]">
                  {String(index + 1).padStart(2, '0')}
                </p>
                <h3 className="mt-8 text-[1.05rem] font-medium tracking-[-0.02em]">{step.title}</h3>
                <p className="mt-2.5 text-[13px] leading-relaxed text-[#f3efe5]/50">{step.body}</p>
              </article>
            </Reveal>
          ))}
        </div>

        <Reveal delay={160}>
          <div className="mt-14 flex flex-col gap-4 border-t border-white/10 pt-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[12px] text-[#f3efe5]/45">
              Every plan includes tenant isolation, cited answers, and the audit trail.
            </p>
            <Link
              href="/help"
              className="inline-flex items-center gap-2 text-sm font-medium text-[#f3efe5]/85 transition-colors hover:text-[#d9a75f]"
            >
              Read the field guide <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

export default HowItWorks
