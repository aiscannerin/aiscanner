import { LegalLayout, Section, P, Ul, Highlight } from '../components/legal/LegalLayout'

export default function PrivacyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      subtitle="How we collect, use, and protect your personal information."
      lastUpdated="May 2026"
      accent="#00f1fe"
    >

      <Highlight
        color="rgba(0,241,254,0.06)"
        border="rgba(0,241,254,0.18)"
        textColor="#00d0e0"
      >
        We do not sell your personal data. We collect only what is necessary to operate the
        Platform and improve your experience.
      </Highlight>

      <Section title="1. Information We Collect">
        <P><strong style={{ color: '#e1e2ee' }}>Account information</strong></P>
        <Ul items={[
          'Full name, username, email address',
          'Phone number and date of birth (for account verification)',
          'Gender and trading experience (optional profile fields)',
          'Address (optional)',
        ]} />
        <P><strong style={{ color: '#e1e2ee' }}>Usage information</strong></P>
        <Ul items={[
          'Scanner parameters you configure (universe, timeframe, filters)',
          'Scan jobs you run and result data generated',
          'Pages and features you access within the Platform',
        ]} />
        <P><strong style={{ color: '#e1e2ee' }}>Payment information</strong></P>
        <P>
          We do not store your card details. Payment processing is handled entirely by Razorpay.
          We store only the Razorpay order ID, payment ID, and subscription status in our database.
        </P>
      </Section>

      <Section title="2. How We Use Your Information">
        <Ul items={[
          'To create and manage your account',
          'To process subscription payments and issue access to paid tools',
          'To deliver OTP verification emails via Brevo transactional email',
          'To improve scanner accuracy and platform features',
          'To send account-related notifications (subscription expiry, security alerts)',
          'To comply with applicable legal obligations',
        ]} />
        <P>
          We do not use your data to send unsolicited marketing emails.
          Transactional emails only.
        </P>
      </Section>

      <Section title="3. Third-Party Services">
        <P>We use the following third-party services to operate the Platform:</P>
        <Ul items={[
          'Razorpay — payment processing (governed by Razorpay\'s privacy policy)',
          'Brevo (formerly Sendinblue) — transactional email delivery for OTPs',
          'PostgreSQL — primary database, hosted on our secured servers',
          'Redis — session and task queue management',
        ]} />
        <P>
          Each third-party service operates under its own privacy policy. We encourage
          you to review them.
        </P>
      </Section>

      <Section title="4. Data Storage and Security">
        <Ul items={[
          'Your data is stored on servers located in India.',
          'Passwords are hashed using bcrypt and are never stored in plaintext.',
          'All API communication is encrypted in transit (HTTPS/TLS).',
          'Access tokens are short-lived JWTs; refresh tokens are hashed before storage.',
          'We conduct periodic security reviews of our systems.',
        ]} />
      </Section>

      <Section title="5. Data Retention">
        <P>
          We retain your account data for as long as your account is active. If you request
          account deletion, we will remove your personal data within 30 days, except where
          retention is required by law (e.g., payment records for tax compliance).
        </P>
      </Section>

      <Section title="6. Your Rights">
        <P>You have the right to:</P>
        <Ul items={[
          'Access the personal data we hold about you',
          'Correct inaccurate or incomplete personal data',
          'Request deletion of your account and associated personal data',
          'Withdraw consent where processing is based on consent',
          'Lodge a complaint with the relevant data protection authority',
        ]} />
        <P>
          To exercise any of these rights, contact us at{' '}
          <a href="mailto:support@stophunterpro.com" style={{ color: '#b3c5ff', textDecoration: 'none' }}>
            support@stophunterpro.com
          </a>.
        </P>
      </Section>

      <Section title="7. Cookies">
        <P>
          Stop Hunter Pro does not currently use tracking or advertising cookies. We use
          browser localStorage only to store authentication tokens for session management.
          You may clear this at any time by logging out or clearing your browser storage.
        </P>
      </Section>

      <Section title="8. Changes to This Policy">
        <P>
          We may update this Privacy Policy from time to time. We will notify you of significant
          changes via email or a prominent notice within the Platform. The "Last updated" date
          at the top of this page reflects the most recent revision.
        </P>
      </Section>

      <Section title="9. Contact">
        <P>
          For privacy-related enquiries, contact us at{' '}
          <a href="mailto:privacy@stophunterpro.com" style={{ color: '#b3c5ff', textDecoration: 'none' }}>
            privacy@stophunterpro.com
          </a>
          {' '}or visit our{' '}
          <a href="/support" style={{ color: '#b3c5ff', textDecoration: 'none' }}>Support page</a>.
        </P>
      </Section>

    </LegalLayout>
  )
}
