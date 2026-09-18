"""Constraint and integrity tests (section 78).

Proves at the database layer:

- UNIQUE(student_id, sense_id) rejects duplicate learning records;
- foreign keys reject dangling references;
- other uniqueness rules (set names, CEFR evidence per source) hold.

Uses real transactions rolled back after each test (no data pollution).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    CefrEvidence,
    CEFRLevel,
    LearningState,
    Student,
    StudentVocabulary,
    Teacher,
    VocabularySense,
    VocabularySet,
)
from app.db.session import make_session
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture(name="db")
def db_fixture():
    """Session whose transaction is always rolled back."""
    session = make_session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(name="teacher")
def teacher_fixture(db):
    t = Teacher(email=f"t-{uuid.uuid4().hex[:10]}@example.com", password_hash="x", display_name="T")
    db.add(t)
    db.flush()
    return t


@pytest.fixture(name="student")
def student_fixture(db, teacher):
    s = Student(teacher_id=teacher.id, display_name="John")
    db.add(s)
    db.flush()
    return s


@pytest.fixture(name="senses")
def senses_fixture(db):
    """BANK financial + BANK river: different senses of the same word."""
    s1 = VocabularySense(
        sense_key="bank|noun|financial_institution",
        headword="bank",
        headword_normalized="bank",
    )
    s2 = VocabularySense(
        sense_key="bank|noun|side_of_river",
        headword="bank",
        headword_normalized="bank",
    )
    db.add_all([s1, s2])
    db.flush()
    return s1, s2


class TestDuplicateStudentSense:
    """The mandatory duplicate-prevention constraint (sections 28-29)."""

    def test_duplicate_sense_for_same_student_rejected(self, db, student, senses) -> None:
        s1, _ = senses
        db.add(StudentVocabulary(student_id=student.id, sense_id=s1.id))
        db.flush()
        db.add(StudentVocabulary(student_id=student.id, sense_id=s1.id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_same_sense_ok_for_two_students(self, db, teacher, senses) -> None:
        s1, _ = senses
        john = Student(teacher_id=teacher.id, display_name="John")
        mary = Student(teacher_id=teacher.id, display_name="Mary")
        db.add_all([john, mary])
        db.flush()
        db.add(StudentVocabulary(student_id=john.id, sense_id=s1.id))
        db.add(StudentVocabulary(student_id=mary.id, sense_id=s1.id))
        db.flush()  # must not raise

    def test_same_word_different_senses_ok(self, db, student, senses) -> None:
        s1, s2 = senses
        db.add(StudentVocabulary(student_id=student.id, sense_id=s1.id))
        db.add(StudentVocabulary(student_id=student.id, sense_id=s2.id))
        db.flush()  # both BANK senses allowed for one student


class TestForeignKeys:
    """Dangling references are rejected by the database."""

    def test_student_vocabulary_requires_real_student(self, db, senses) -> None:
        s1, _ = senses
        db.add(StudentVocabulary(student_id=uuid.uuid4(), sense_id=s1.id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_student_vocabulary_requires_real_sense(self, db, student) -> None:
        db.add(StudentVocabulary(student_id=student.id, sense_id=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestOtherUniqueness:
    """Supporting uniqueness rules."""

    def test_sense_key_unique(self, db, senses) -> None:
        s1, _ = senses
        dup = VocabularySense(
            sense_key=s1.sense_key,
            headword="bank",
            headword_normalized="bank",
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_set_name_unique_per_teacher(self, db, teacher) -> None:
        db.add(VocabularySet(teacher_id=teacher.id, name="Travel"))
        db.flush()
        db.add(VocabularySet(teacher_id=teacher.id, name="Travel"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_cefr_evidence_one_per_source(self, db, senses) -> None:
        from app.db.models import VocabularySource

        s1, _ = senses
        src = VocabularySource(key="cefrj", name="CEFR-J 1.5")
        db.add(src)
        db.flush()
        db.add(
            CefrEvidence(
                sense_id=s1.id,
                source_id=src.id,
                cefr_level=CEFRLevel.A2,
            )
        )
        db.flush()
        db.add(
            CefrEvidence(
                sense_id=s1.id,
                source_id=src.id,
                cefr_level=CEFRLevel.B2,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestLearningStateEnum:
    """Learning states persist as their canonical string values."""

    def test_state_roundtrip(self, db, student, senses) -> None:
        s1, _ = senses
        sv = StudentVocabulary(
            student_id=student.id,
            sense_id=s1.id,
            learning_state=LearningState.MASTERED,
        )
        db.add(sv)
        db.flush()
        db.expire_all()
        fetched = db.execute(
            select(StudentVocabulary).where(StudentVocabulary.id == sv.id)
        ).scalar_one()
        assert fetched.learning_state == LearningState.MASTERED
