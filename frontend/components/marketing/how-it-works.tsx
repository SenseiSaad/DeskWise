import { Reveal } from '@/components/reveal'

const STEPS = [
  { num: '01', title: 'Sign up', body: 'Create your company account in under a minute. No card needed.' },
  { num: '02', title: 'Upload documents', body: 'Drag in your handbooks, policies and contracts. PDF, Word, Excel and scans all work.' },
  { num: '03', title: 'Ask', body: 'Ask in plain words. Get the answer, the page it came from, and forms ready to send.' },
]

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 py-20 sm:py-28" aria-labelledby="how-heading">
      <div className="container-page">
        <div className="max-w-2xl">
          <p className="eyebrow">How it works</p>
          <h2 id="how-heading" className="display-lg mt-5">
            Up and running in <span className="serif text-accent">five minutes.</span>
          </h2>
        </div>
        <ol className="mt-14 grid gap-10 md:grid-cols-3 md:gap-8">
          {STEPS.map((s, i) => (
            <li key={s.num}>
              <Reveal delay={i * 90}>
                <span aria-hidden className="font-display text-8xl font-bold leading-none tracking-tighter">
                  {s.num}
                </span>
                <div className="mt-4 border-t border-foreground/80 pt-5">
                  <h3 className="text-xl font-semibold">{s.title}</h3>
                  <p className="mt-2 text-base leading-relaxed text-muted-foreground">{s.body}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

export default HowItWorks
