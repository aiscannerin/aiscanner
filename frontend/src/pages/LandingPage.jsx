import { Navbar }          from '../components/landing/Navbar'
import { HeroSection }     from '../components/landing/HeroSection'
import { PlatformOverview } from '../components/landing/PlatformOverview'
import { HowItWorks }      from '../components/landing/HowItWorks'
import { ScannerLibrary }  from '../components/landing/ScannerLibrary'
import { PricingSection }  from '../components/landing/PricingSection'
import { DashboardPreview } from '../components/landing/DashboardPreview'
import { FinalCTA }        from '../components/landing/FinalCTA'
import { Footer }          from '../components/landing/Footer'

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-on-surface">
      <Navbar />
      <main>
        <HeroSection />
        <PlatformOverview />
        <HowItWorks />
        <ScannerLibrary />
        <DashboardPreview />
        <PricingSection />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  )
}
