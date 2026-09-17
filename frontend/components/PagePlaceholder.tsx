/**
 * Shared placeholder page shell for routes whose UI arrives in later phases
 * (see ROUTE_DEFINITIONS). Keeps the route structure real and navigable
 * while honestly stating implementation status — no fake features.
 */

interface PagePlaceholderProps {
  title: string;
  phase: number;
  description: string;
}

export function PagePlaceholder({ title, phase, description }: PagePlaceholderProps) {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-neutral-600">{description}</p>
      <p className="mt-6 inline-block rounded bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-700">
        Not implemented yet — planned for phase {phase}
      </p>
    </main>
  );
}
