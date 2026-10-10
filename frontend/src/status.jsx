export const STATUS = {
  READY_FOR_REVIEW: {
    label: 'Ready for review',
    badge: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20',
    dot: 'bg-emerald-500',
    help: 'All fields present, match found, price verified, compliance checked. Needs human approval.',
  },
  NEEDS_CLARIFICATION: {
    label: 'Needs clarification',
    badge: 'bg-amber-100 text-amber-800 ring-amber-600/20',
    dot: 'bg-amber-500',
    help: 'Missing or ambiguous field that would change the match or price. A question for the buyer is drafted.',
  },
  NO_COMPATIBLE_MATCH: {
    label: 'No compatible match',
    badge: 'bg-rose-100 text-rose-800 ring-rose-600/20',
    dot: 'bg-rose-500',
    help: 'No catalog item passed the hard filters. No substitute is chosen.',
  },
  PRICE_UNVERIFIED: {
    label: 'Price unverified',
    badge: 'bg-orange-100 text-orange-800 ring-orange-600/20',
    dot: 'bg-orange-500',
    help: 'Match found but no market benchmark to verify the price against.',
  },
  COMPLIANCE_REVIEW: {
    label: 'Compliance review',
    badge: 'bg-violet-100 text-violet-800 ring-violet-600/20',
    dot: 'bg-violet-500',
    help: 'A required document (MTR, origin, certification) has no evidence.',
  },
  PARSER_REVIEW: {
    label: 'Parser review',
    badge: 'bg-slate-200 text-slate-700 ring-slate-500/20',
    dot: 'bg-slate-400',
    help: 'Text could not be reliably parsed into a line item.',
  },
}

export const money = (v) =>
  v == null ? '—' : v.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export function StatusBadge({ status }) {
  const s = STATUS[status]
  return (
    <span
      title={s.help}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${s.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}
