/**
 * Lightweight className merger — joins truthy class strings.
 * No extra dependencies needed for this project's complexity.
 */
export function cn(...classes) {
  return classes.filter(Boolean).join(' ')
}
