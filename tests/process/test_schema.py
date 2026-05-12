import pytest
from datetime import datetime, timedelta
from backend.process.schema import (
    Vote,
    VoteEvent,
    Attendance,
    VoteOption,
    AttendanceStatus,
    Bill,
    BillStep,
    BillCongresistas,
    Congresista,
    Organization,
    Membership,
)
from backend import (
    TypeRoleBill,
    Proponents,
    TypeBillStep,
    LegPeriod,
    TypeOrganization,
    RoleOrganization,
    VoteResult,
    TypeMajority,
    TypeCommittee,
)


@pytest.fixture
def sample_votes():
    return [
        Vote(vote_event_id="ev1", voter_id=1, option=VoteOption.SI, bancada_id=10),
        Vote(vote_event_id="ev1", voter_id=2, option=VoteOption.NO, bancada_id=10),
        Vote(vote_event_id="ev1", voter_id=3, option=VoteOption.SI, bancada_id=20),
    ]


@pytest.fixture
def sample_attendance():
    return [
        Attendance(
            org_id=1, event_id="ev1", attendee_id=1, status=AttendanceStatus.PRESENTE
        ),
        Attendance(
            org_id=1, event_id="ev1", attendee_id=2, status=AttendanceStatus.AUSENTE
        ),
        Attendance(
            org_id=1, event_id="ev1", attendee_id=3, status=AttendanceStatus.PRESENTE
        ),
    ]


@pytest.fixture
def sample_vote_event(sample_votes, sample_attendance):
    return VoteEvent(
        leg_period=LegPeriod.PERIODO_2021_2026,
        bill_or_motion="Motion",
        bill_motion_id="123",
        date=datetime.now(),
        result=VoteResult.APROBADO,
        majority_type=TypeMajority.SIMPLE,
        votes=sample_votes,
        attendance=sample_attendance,
    )


@pytest.fixture
def sample_bill():
    return Bill(
        id="b001",
        title="Ley de Prueba",
        summary_congreso="Resumen",
        observations="Observaciones",
        status="En trámite",
        proponent=Proponents.PODER_EJECUTIVO,
        author_name=None,
        author_web=None,
        bancada_name="Bancada Test",
        bill_approved=True,
        summary_oc="Resumen OC",
    )


def test_vote_event_counts(sample_vote_event):
    vote_event = sample_vote_event
    counts = vote_event.get_counts()
    assert counts[VoteOption.SI] == 2
    assert counts[VoteOption.NO] == 1


def test_vote_event_counts_by_bancada(sample_vote_event):
    vote_event = sample_vote_event
    counts_by_bancada = vote_event.get_counts_by_bancada()
    assert counts_by_bancada[10][VoteOption.SI] == 1
    assert counts_by_bancada[10][VoteOption.NO] == 1
    assert counts_by_bancada[20][VoteOption.SI] == 1


def test_attendance_summary(sample_vote_event):
    vote_event = sample_vote_event
    summary = vote_event.get_attendance_summary()
    assert summary[AttendanceStatus.PRESENTE] == 2
    assert summary[AttendanceStatus.AUSENTE] == 1


def test_bill_creation(sample_bill):
    bill = sample_bill
    assert bill.author_name is None
    assert bill.proponent == Proponents.PODER_EJECUTIVO


def test_membership_date_validation():
    with pytest.raises(ValueError):
        Membership(
            cong_name="Jaime",
            org_name="Committee",
            org_type=TypeOrganization.COMMITTEE,
            leg_period=LegPeriod.PERIODO_2021_2026,
            role=RoleOrganization.MIEMBRO,
            time_stamp=datetime.now(),
            start_date=datetime.now(),
            end_date=datetime.now() - timedelta(days=1),
        )


def test_congresista_creation():
    congresista = Congresista(
        full_name="Ana Maria Torres Torres",
        first_name="Ana Maria",
        last_name="Torres Torres",
        dni="12345678",
        photo_url="https://example.com/photo",
        website="https://example.com",
    )
    assert congresista.full_name == "Ana Maria Torres Torres"


def test_organization_creation():
    org = Organization(
        org_name="Comisión de Justicia",
        org_type=TypeOrganization.COMMITTEE,
        org_subtype=TypeCommittee.COM_INVESTIGADORA,
        org_link="http://congreso.gob.pe/comision_investigadora",
    )
    assert org.org_name == "Comisión de Justicia"


def test_bill_congresistas_creation():
    relation = BillCongresistas(
        bill_id="b001",
        nombre="Juan Perez",
        leg_period=LegPeriod.PERIODO_2021_2026,
        role_type=TypeRoleBill.ADHERENTE,
    )
    assert relation.role_type == TypeRoleBill.ADHERENTE


def test_bill_step_creation():
    step = BillStep(
        bill_id="b001",
        step_id=123,
        step_type=TypeBillStep.VOTACION,
        vote_step=True,
        vote_event_id=None,
        step_date=datetime.now().date(),
        step_detail="Se presentó el proyecto",
        step_committees=[],
    )
    assert step.step_detail == "Se presentó el proyecto"
