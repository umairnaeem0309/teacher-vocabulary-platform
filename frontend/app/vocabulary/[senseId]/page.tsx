"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { fetchSenseDetail } from "@/lib/search-client";
import { ROUTES } from "@/lib/routes";

/**
 * Single sense details (section 23/54): headword, forms, definitions,
 * Polish translations, examples, categories, frequency and priority
 * evidence — everything the import pipeline stores for one sense.
 */
export default function SenseDetailsPage({
  params,
}: {
  params: Promise<{ senseId: string }>;
}) {
  // Next.js 15+ async params; unwrap with React.use().
  const { senseId } = use(params);

  const detail = useQuery({
    queryKey: ["vocabulary", "sense", senseId],
    queryFn: () => fetchSenseDetail(senseId),
    retry: false,
  });

  if (detail.isError) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-red-600">This sense could not be loaded.</p>
        <Link href={ROUTES.vocabulary} className="mt-4 inline-block underline">
          ← Back to vocabulary
        </Link>
      </main>
    );
  }

  const d = detail.data;
  const sense = d?.sense;

  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <Link href={ROUTES.vocabulary} className="text-sm underline">
        ← Back to vocabulary
      </Link>

      {detail.isLoading || !sense ? (
        <p className="mt-8 text-neutral-500">Loading…</p>
      ) : (
        <>
          <h1 className="mt-4 text-3xl font-semibold">{sense.headword}</h1>
          <div className="mt-1 flex flex-wrap gap-3 text-sm text-neutral-600">
            {sense.part_of_speech && <span>{sense.part_of_speech}</span>}
            {sense.cefr_level && <span>CEFR {sense.cefr_level}</span>}
            {sense.priority_level && (
              <span>
                Priority {sense.priority_level}
                {sense.priority_score !== null && ` (${sense.priority_score.toFixed(3)})`}
              </span>
            )}
            {sense.priority_version && <span>{sense.priority_version}</span>}
          </div>

          {d.forms.length > 0 && (
            <Section title="Forms">
              {d.forms.map((f) => (
                <span key={f.form} className="mr-2 inline-block rounded bg-neutral-100 px-2 py-0.5">
                  {f.form}
                  {f.is_lemma && <em className="ml-1 text-xs text-neutral-500">lemma</em>}
                </span>
              ))}
            </Section>
          )}

          {d.definitions.length > 0 && (
            <Section title="Definitions">
              <ul className="list-disc pl-5">
                {d.definitions.map((def, i) => (
                  <li key={i}>
                    {def.definition}{" "}
                    <span className="text-xs text-neutral-400">[{def.source}]</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {d.translations.length > 0 && (
            <Section title="Polish translations">
              <ul className="list-disc pl-5">
                {d.translations.map((t, i) => (
                  <li key={i}>
                    {t.translation}
                    {t.confidence !== null && (
                      <span className="text-xs text-neutral-400">
                        {" "}
                        ({t.confidence.toFixed(2)})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {d.examples.length > 0 && (
            <Section title="Examples">
              <ul className="list-disc pl-5">
                {d.examples.map((ex, i) => (
                  <li key={i}>
                    <em>{ex.example}</em>{" "}
                    <span className="text-xs text-neutral-400">[{ex.source}]</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {d.categories.length > 0 && (
            <Section title="Categories">
              {d.categories.map((c) => (
                <span key={c.key} className="mr-2 inline-block rounded bg-neutral-100 px-2 py-0.5">
                  {c.name}
                </span>
              ))}
            </Section>
          )}

          {d.frequency.length > 0 && (
            <Section title="Frequency evidence">
              <ul className="list-disc pl-5">
                {d.frequency.map((f, i) => (
                  <li key={i}>
                    {f.source_name ?? f.source_key}: rank {f.rank ?? "—"}
                    {f.frequency_per_million !== null &&
                      `, ${f.frequency_per_million.toFixed(2)} per million`}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {d.priorities.length > 0 && (
            <Section title="Priority versions">
              <ul className="list-disc pl-5">
                {d.priorities.map((p) => (
                  <li key={p.version}>
                    {p.version}: score {p.score.toFixed(3)}, level {p.level}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <p className="mt-8 text-xs text-neutral-400">
            sense_key {sense.sense_key} · processing {sense.processing_version}
          </p>
        </>
      )}
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}
