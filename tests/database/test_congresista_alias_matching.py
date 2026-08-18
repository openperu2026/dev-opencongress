"""Tests for congresista name matching and alias lookup."""

import pytest

from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core
from backend.process.utils import normalize_name


class TestNormalizeName:
    """Tests for normalize_name function."""

    def test_normalize_strips_accents(self):
        """Accents should be removed."""
        assert normalize_name("José María") == "jose maria"
        assert normalize_name("Jáuregui Martínez") == "jauregui martinez"

    def test_normalize_removes_punctuation(self):
        """Commas and periods should be removed."""
        assert (
            normalize_name("Smith, John") == "john smith"
        )  # sorted: john before smith
        assert normalize_name("J. R. Smith") == "j r smith"

    def test_normalize_lowercases(self):
        """Should convert to lowercase."""
        assert normalize_name("JOHN SMITH") == "john smith"

    def test_normalize_sorts_tokens_by_default(self):
        """Tokens should be alphabetically sorted by default."""
        assert normalize_name("John Smith") == "john smith"
        assert normalize_name("Smith John") == "john smith"
        # Both orderings produce the same normalized key
        assert normalize_name("Jáuregui Martínez de Aguayo") == normalize_name(
            "Aguayo de Martínez Jáuregui"
        )

    def test_normalize_preserves_token_order_when_unsorted(self):
        """With sort_tokens=False, word order should match input."""
        assert normalize_name("John Smith", sort_tokens=False) == "john smith"
        assert normalize_name("Smith John", sort_tokens=False) == "smith john"
        # Different orderings produce different normalized keys
        assert normalize_name(
            "First Second Third", sort_tokens=False
        ) != normalize_name("Third Second First", sort_tokens=False)

    def test_normalize_strips_whitespace(self):
        """Leading/trailing whitespace should be removed."""
        assert normalize_name("  John Smith  ") == "john smith"
        assert normalize_name("  JOSÉ MARÍA  ") == "jose maria"

    def test_normalize_returns_empty_string_on_empty_input(self):
        """Empty/whitespace-only input should return empty string."""
        assert normalize_name("") == ""
        assert normalize_name("   ") == ""


class TestSaveAlias:
    """Tests for save_alias function."""

    @pytest.fixture
    def congresista(self, session):
        """Create a test congresista."""
        cong = db_models.Congresista(
            full_name="Carlos Ernesto Bustamante Donayre",
            first_name="Carlos",
            last_name="Bustamante Donayre",
            dni="12345678",
            gender="M",
            photo_url="http://example.com/photo.jpg",
            website="http://example.com",
        )
        session.add(cong)
        session.flush()
        return cong

    def test_save_alias_creates_new_alias(self, session, congresista):
        """save_alias should create a new alias."""
        created = crud_core.save_alias(
            session,
            congresista,
            "ERNESTO BUSTAMANTE",
        )
        session.flush()

        assert created is True
        alias = (
            session.query(db_models.CongresistaAlias)
            .filter_by(congresista_id=congresista.id)
            .first()
        )
        assert alias is not None
        # Normalized: "bustamante ernesto" (sorted tokens)
        assert alias.name == "bustamante ernesto"

    def test_save_alias_idempotent(self, session, congresista):
        """Second call with same alias should not create duplicate."""
        created1 = crud_core.save_alias(session, congresista, "ERNESTO BUSTAMANTE")
        session.flush()
        assert created1 is True

        created2 = crud_core.save_alias(session, congresista, "ERNESTO BUSTAMANTE")
        session.flush()
        assert created2 is False

        aliases = (
            session.query(db_models.CongresistaAlias)
            .filter_by(congresista_id=congresista.id)
            .all()
        )
        assert len(aliases) == 1

    def test_save_alias_ignores_empty_normalized_name(self, session, congresista):
        """save_alias should ignore names that normalize to empty."""
        created1 = crud_core.save_alias(session, congresista, "")
        assert created1 is False

        created2 = crud_core.save_alias(session, congresista, "   ")
        assert created2 is False

        session.flush()

        aliases = (
            session.query(db_models.CongresistaAlias)
            .filter_by(congresista_id=congresista.id)
            .all()
        )
        assert len(aliases) == 0

    def test_save_alias_with_accents_and_punctuation(self, session, congresista):
        """save_alias should normalize accents and punctuation."""
        created = crud_core.save_alias(
            session,
            congresista,
            "BUSTAMANTE, Ernésto",
        )
        session.flush()

        assert created is True
        alias = (
            session.query(db_models.CongresistaAlias)
            .filter_by(congresista_id=congresista.id)
            .first()
        )
        assert alias is not None
        # Normalized: "bustamante ernesto" (accents stripped, comma removed, sorted)
        assert alias.name == "bustamante ernesto"


class TestFindCongresistaWebsite:
    """Tests for website matching in find_congresista."""

    @pytest.fixture
    def congresista(self, session):
        """Create a test congresista."""
        cong = db_models.Congresista(
            full_name="Test Person",
            first_name="Test",
            last_name="Person",
            dni="11111111",
            gender="M",
            photo_url="http://example.com/photo.jpg",
            website="http://example.com/test-person",
        )
        session.add(cong)
        session.flush()
        return cong

    def test_find_congresista_by_website(self, session, congresista):
        """Should match by exact website URL."""
        result = crud_core.find_congresista(
            session,
            "garbage name",
            website="http://example.com/test-person",
        )
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_website_not_stripped(self, session, congresista):
        """Website matching should strip input but use exact match."""
        result = crud_core.find_congresista(
            session,
            "garbage name",
            website="  http://example.com/test-person  ",
        )
        assert result is not None
        assert result.id == congresista.id


class TestFindCongresistaAlias:
    """Tests for alias matching in find_congresista."""

    @pytest.fixture
    def congresista(self, session):
        """Create a test congresista."""
        cong = db_models.Congresista(
            full_name="María de los Milagros Jáuregui Martínez de Aguayo",
            first_name="María",
            last_name="Jáuregui Martínez de Aguayo",
            dni="22222222",
            gender="F",
            photo_url="http://example.com/photo.jpg",
            website="http://example.com/maria",
        )
        session.add(cong)
        session.flush()

        # Add some known aliases (each normalizes to a different key)
        crud_core.save_alias(session, cong, "JÁUREGUI MARTÍNEZ DE AGUAYO, MARIA")
        crud_core.save_alias(session, cong, "MARIA LUZ JAUREGUI")  # Different token set
        session.flush()
        session.commit()

        return cong

    def test_find_congresista_by_alias_exact_match(self, session, congresista):
        """Should match via alias exact match (after normalization)."""
        # Alias was saved; tokens normalize to "aguayo de jauregui maria martinez" (sorted)
        result = crud_core.find_congresista(
            session,
            "JÁUREGUI MARTÍNEZ DE AGUAYO, MARIA",  # Different word order, with accents
        )
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_alias_overrides_fuzzy(self, session, congresista):
        """Alias match should be returned before fuzzy match is attempted."""
        # Even with tokens in a different order, if an alias exists it should be found.
        result = crud_core.find_congresista(
            session,
            "MARIA LUZ JAUREGUI",  # Matches an alias
        )
        assert result is not None
        assert result.id == congresista.id


class TestGivenNameFirst:
    """Tests for the _given_name_first helper (SURNAME, GIVEN -> GIVEN SURNAME)."""

    def test_reorders_on_comma(self):
        assert (
            crud_core._given_name_first("Zeballos Aponte, Jorge")
            == "Jorge Zeballos Aponte"
        )

    def test_strips_whitespace_around_comma(self):
        assert (
            crud_core._given_name_first("Zeballos Aponte ,  Jorge ")
            == "Jorge Zeballos Aponte"
        )

    def test_no_comma_returns_unchanged(self):
        assert crud_core._given_name_first("Jorge Zeballos Aponte") == (
            "Jorge Zeballos Aponte"
        )

    def test_empty_string_returns_unchanged(self):
        assert crud_core._given_name_first("") == ""


class TestFindCongresistaFuzzy:
    """Tests for fuzzy matching in find_congresista."""

    @pytest.fixture
    def congresista(self, session):
        """Create a test congresista."""
        cong = db_models.Congresista(
            full_name="Jorge Zeballos Aponte",
            first_name="Jorge",
            last_name="Zeballos Aponte",
            dni="33333333",
            gender="M",
            photo_url="http://example.com/photo.jpg",
            website="http://example.com/jorge",
        )
        session.add(cong)
        session.flush()
        return cong

    def test_find_congresista_fuzzy_exact_match(self, session, congresista):
        """Fuzzy path should match exact canonical name."""
        result = crud_core.find_congresista(session, "Jorge Zeballos Aponte")
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_fuzzy_case_insensitive(self, session, congresista):
        """Fuzzy match should be case-insensitive."""
        result = crud_core.find_congresista(session, "JORGE ZEBALLOS APONTE")
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_fuzzy_accents_ignored(self, session, congresista):
        """Fuzzy match should ignore accents."""
        # Create another congresista with accents
        cong2 = db_models.Congresista(
            full_name="Rocío Torres Salinas",
            first_name="Rocío",
            last_name="Torres Salinas",
            dni="44444444",
            gender="F",
            photo_url="http://example.com/photo2.jpg",
            website="http://example.com/rocio",
        )
        session.add(cong2)
        session.flush()

        result = crud_core.find_congresista(session, "Rocio Torres Salinas")
        assert result is not None
        assert result.id == cong2.id

    def test_find_congresista_fuzzy_returns_none_on_no_match(
        self, session, congresista
    ):
        """Fuzzy match should return None if no match above threshold."""
        result = crud_core.find_congresista(session, "Completely Different Name")
        assert result is None

    def test_find_congresista_fuzzy_handles_surname_first_format(
        self, session, congresista
    ):
        """Roster-format 'SURNAME(S), GIVEN NAME(S)' input should match the
        same congresista as the canonical 'GIVEN NAME(S) SURNAME(S)' order
        -- this is the production bug fixed 2026-08-18 (91% of measured
        name-match failures were this exact word-order mismatch)."""
        result = crud_core.find_congresista(session, "Zeballos Aponte, Jorge")
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_fuzzy_surname_first_with_accents_and_case(
        self, session, congresista
    ):
        """Surname-first reordering should compose with existing accent/case
        normalization, not bypass it."""
        result = crud_core.find_congresista(session, "ZEBALLOS APONTE, JORGE")
        assert result is not None
        assert result.id == congresista.id

    def test_find_congresista_returns_best_match(self, session):
        """Fuzzy match should return the highest-scoring match."""
        cong1 = db_models.Congresista(
            full_name="John Smith",
            first_name="John",
            last_name="Smith",
            dni="55555555",
            gender="M",
            photo_url="http://example.com/photo1.jpg",
            website="http://example.com/john1",
        )
        cong2 = db_models.Congresista(
            full_name="John Smithson",
            first_name="John",
            last_name="Smithson",
            dni="66666666",
            gender="M",
            photo_url="http://example.com/photo2.jpg",
            website="http://example.com/john2",
        )
        session.add_all([cong1, cong2])
        session.flush()

        # SQLite stub jarowinkler returns 1.0 on exact match, 0.0 on difference.
        # So "John Smith" will match cong1 exactly, returning id of cong1.
        result = crud_core.find_congresista(session, "John Smith")
        assert result is not None
        assert result.id == cong1.id


class TestFindCongresistaReturnsBestOption:
    """Tests for matching priority (website > alias > fuzzy)."""

    @pytest.fixture
    def two_congresistas(self, session):
        """Create two test congresistas."""
        cong1 = db_models.Congresista(
            full_name="Alice Johnson",
            first_name="Alice",
            last_name="Johnson",
            dni="77777777",
            gender="F",
            photo_url="http://example.com/photo1.jpg",
            website="http://example.com/alice",
        )
        cong2 = db_models.Congresista(
            full_name="Bob Johnson",
            first_name="Bob",
            last_name="Johnson",
            dni="88888888",
            gender="M",
            photo_url="http://example.com/photo2.jpg",
            website="http://example.com/bob",
        )
        session.add_all([cong1, cong2])
        session.flush()

        # Add alias for cong2 that looks similar to cong1's name
        crud_core.save_alias(session, cong2, "Alice Johnson")
        session.flush()
        session.commit()

        return cong1, cong2

    def test_website_takes_precedence_over_alias(self, session, two_congresistas):
        """Website match should win over alias or fuzzy."""
        cong1, cong2 = two_congresistas
        result = crud_core.find_congresista(
            session,
            "Some Random Name",
            website="http://example.com/alice",
        )
        assert result.id == cong1.id

    def test_alias_takes_precedence_over_fuzzy(self, session, two_congresistas):
        """Alias match should win over fuzzy match."""
        cong1, cong2 = two_congresistas
        # "Alice Johnson" will match an alias to cong2 exactly
        result = crud_core.find_congresista(session, "Alice Johnson")
        assert result.id == cong2.id
