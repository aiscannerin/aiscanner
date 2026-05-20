import { LegalLayout, Section, P, Ul } from '../components/legal/LegalLayout'

export default function TermsPage() {
  return (
    <LegalLayout
      title="Terms of Service"
      subtitle="Please read these terms carefully before using Stop Hunter Pro."
      lastUpdated="May 2026"
      accent="#b3c5ff"
    >

      <Section title="1. Acceptance of Terms">
        <P>
          By accessing or using Stop Hunter Pro ("the Platform", "we", "us"), you agree to be bound
          by these Terms of Service. If you do not agree to any part of these terms, you may not
          use the Platform.
        </P>
        <P>
          We reserve the right to update these terms at any time. Continued use of the Platform
          after changes constitutes acceptance of the revised terms.
        </P>
      </Section>

      <Section title="2. Description of Service">
        <P>
          Stop Hunter Pro is a market scanning and research platform designed for Indian equity
          markets (NSE and BSE). The Platform provides tools to identify technical patterns,
          order-flow signals, and liquidity events on historical and real-time price data.
        </P>
        <P>
          <strong style={{ color: '#e1e2ee' }}>The Platform is a research tool only.</strong>{' '}
          It does not provide financial advice, investment recommendations, or trading signals
          intended to be followed without independent judgment. See our Risk Disclaimer for
          full details.
        </P>
      </Section>

      <Section title="3. User Accounts">
        <Ul items={[
          'You must be at least 18 years old to create an account.',
          'You are responsible for maintaining the security of your account credentials.',
          'You must provide accurate and complete information during registration.',
          'One account per individual. Sharing accounts is not permitted.',
          'We reserve the right to suspend or terminate accounts that violate these terms.',
        ]} />
      </Section>

      <Section title="4. Subscriptions and Payments">
        <P>
          Stop Hunter Pro offers Free, Pro, and Expert subscription tiers. Paid subscriptions
          are billed on a monthly or yearly basis as selected at checkout.
        </P>
        <Ul items={[
          'All payments are processed securely through Razorpay.',
          'Prices are in Indian Rupees (INR) and include applicable taxes.',
          'Subscriptions do not auto-renew; manual renewal is required upon expiry.',
          'Refunds are not provided for partially used subscription periods.',
          'We reserve the right to change pricing with reasonable advance notice.',
        ]} />
      </Section>

      <Section title="5. Prohibited Uses">
        <P>You agree not to:</P>
        <Ul items={[
          'Use the Platform for any unlawful purpose or in violation of applicable laws.',
          'Scrape, crawl, or systematically extract data from the Platform without written permission.',
          'Attempt to reverse-engineer, decompile, or disassemble any part of the Platform.',
          'Share or resell access to your account or any Platform outputs commercially.',
          'Use automated systems (bots, scripts) to interact with the Platform beyond normal use.',
          'Distribute scanner results or signals as financial advice or investment tips.',
        ]} />
      </Section>

      <Section title="6. Intellectual Property">
        <P>
          All content, software, algorithms, scanner logic, visual design, and data on the Platform
          are the exclusive intellectual property of Stop Hunter Pro and its licensors. You are
          granted a limited, non-exclusive, non-transferable licence to access the Platform for
          your personal, non-commercial use during your active subscription.
        </P>
      </Section>

      <Section title="7. Disclaimers and Limitation of Liability">
        <P>
          The Platform is provided "as is" and "as available". We make no warranties of any kind,
          express or implied, including but not limited to fitness for a particular purpose,
          accuracy, or uninterrupted availability.
        </P>
        <P>
          To the maximum extent permitted by law, Stop Hunter Pro shall not be liable for any
          direct, indirect, incidental, consequential, or punitive damages arising from your use
          of the Platform, including but not limited to trading losses.
        </P>
      </Section>

      <Section title="8. Termination">
        <P>
          We may suspend or terminate your access to the Platform at any time, with or without
          notice, for conduct that violates these Terms or is otherwise harmful to the Platform,
          other users, or third parties. Upon termination, your right to use the Platform ceases
          immediately.
        </P>
      </Section>

      <Section title="9. Governing Law">
        <P>
          These Terms shall be governed by and construed in accordance with the laws of India.
          Any disputes arising from these Terms or the use of the Platform shall be subject to
          the exclusive jurisdiction of the courts of India.
        </P>
      </Section>

      <Section title="10. Contact">
        <P>
          For questions about these Terms of Service, please contact us at{' '}
          <a href="mailto:support@stophunterpro.com" style={{ color: '#b3c5ff', textDecoration: 'none' }}>
            support@stophunterpro.com
          </a>
          {' '}or visit our{' '}
          <a href="/support" style={{ color: '#b3c5ff', textDecoration: 'none' }}>Support page</a>.
        </P>
      </Section>

    </LegalLayout>
  )
}
