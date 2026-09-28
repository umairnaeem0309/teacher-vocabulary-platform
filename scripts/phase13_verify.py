import sqlalchemy as sa

e = sa.create_engine("postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform")
with e.connect() as c:
    print("--- totals ---")
    for t in (
        "vocabulary_senses", "vocabulary_forms", "sense_definitions",
        "sense_translations", "sense_examples", "cefr_evidence",
        "frequency_evidence", "vocabulary_flags", "sense_priorities",
        "categories", "sense_categories", "wordnet_synsets",
        "wordnet_relations", "sense_wordnet_links", "vocabulary_sources",
        "sense_embeddings",
    ):
        n = c.execute(sa.text(f"select count(*) from {t}")).scalar()
        print(f"  {t}: {n}")

    key = "bank|noun|f6a4b8f28d34"
    print(f"--- spot: {key} ---")
    rows = c.execute(sa.text(
        "select t.translation, t.confidence from sense_translations t "
        "join vocabulary_senses v on v.id=t.sense_id where v.sense_key=:k"
    ), {"k": key}).fetchall()
    for r in rows:
        print("  trans:", tuple(r))
    rows = c.execute(sa.text(
        "select f.flag from vocabulary_flags f join vocabulary_senses v "
        "on v.id=f.sense_id where v.sense_key=:k"
    ), {"k": key}).fetchall()
    for r in rows:
        print("  flag:", r[0])
    rows = c.execute(sa.text(
        "select p.version, p.score, p.level from sense_priorities p "
        "join vocabulary_senses v on v.id=p.sense_id where v.sense_key=:k "
        "order by p.version"
    ), {"k": key}).fetchall()
    for r in rows:
        print("  prio:", tuple(r))
    rows = c.execute(sa.text(
        "select ca.key from sense_categories sc join categories ca on "
        "ca.id=sc.category_id join vocabulary_senses v on v.id=sc.sense_id "
        "where v.sense_key=:k"
    ), {"k": key}).fetchall()
    for r in rows:
        print("  cat:", r[0])
    rows = c.execute(sa.text(
        "select e.example from sense_examples e join vocabulary_senses v "
        "on v.id=e.sense_id where v.sense_key=:k limit 3"
    ), {"k": key}).fetchall()
    for r in rows:
        print("  ex:", r[0][:60])
    print("--- bank senses by priority ---")
    rows = c.execute(sa.text(
        "select sense_key, cefr_level, priority_level, priority_score from "
        "vocabulary_senses where headword_normalized='bank' order by "
        "priority_score desc limit 4"
    )).fetchall()
    for r in rows:
        print("  ", tuple(r))
    print("--- flag distribution ---")
    rows = c.execute(sa.text(
        "select flag, count(*) from vocabulary_flags group by 1 order by 2 desc"
    )).fetchall()
    for r in rows:
        print("  ", tuple(r))
    print("--- sources ---")
    for r in c.execute(sa.text("select key, name, version from vocabulary_sources order by key")):
        print("  ", tuple(r))
