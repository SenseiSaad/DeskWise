import { SiteHeader } from '@/components/site-header'
import { SiteFooter } from '@/components/site-footer'
import { Hero } from '@/components/marketing/hero'
import { ScrollStory } from '@/components/marketing/scroll-story'
import { HowItWorks } from '@/components/marketing/how-it-works'
import { PricingSection } from '@/components/marketing/pricing-section'
import { FaqSection } from '@/components/marketing/faq-section'
import { FinalCta } from '@/components/marketing/final-cta'

export default function Page() {
  return (
    <main id="main-content" className="min-h-screen overflow-x-clip">
      <SiteHeader />
      <Hero />
      <ScrollStory />
      <HowItWorks />
      <PricingSection showTable={false} />
      <FaqSection />
      <FinalCta />
      <SiteFooter />
    </main>
  )
}
