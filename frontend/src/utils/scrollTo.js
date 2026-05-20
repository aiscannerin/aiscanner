/**
 * Smooth-scroll to a section by its element ID.
 * Falls back gracefully when the section doesn't exist yet.
 * @param {string} id - The element id (without #)
 * @param {number} offset - px to subtract from top (for fixed navbar)
 */
export function scrollToSection(id, offset = 72) {
  const el = document.getElementById(id)
  if (!el) return

  const top = el.getBoundingClientRect().top + window.scrollY - offset
  window.scrollTo({ top, behavior: 'smooth' })
}
