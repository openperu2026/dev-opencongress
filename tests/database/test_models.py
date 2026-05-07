import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from backend.database.models import (
    Base,
    Vote,
    VoteEvent,
    VoteCounts,
    Attendance,
    Bill,
    BillCongresistas,
    BillCommittees,
    BillStep,
    Congresista,
    Organization,
    Membership,
    VoteOption,
    AttendanceStatus,
    RoleTypeBill,
    Proponents,
    LegPeriod,
    Legislature,
    LegislativeYear,
    TypeOrganization,
    RoleOrganization,
    TypeCommittee,
    VoteResult,
    MajorityType,
)
from backend import BillStepType


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_create_organization(session):
    org = Organization(
        leg_period=LegPeriod.PERIODO_2021_2026,
        leg_year=LegislativeYear.YEAR_2021_2022,
        org_name="Congreso del Perú",
        org_type=TypeOrganization.COMISON,
        comm_type=TypeCommittee.COM_ETICA,
        org_link="www.congreso.gob.pe/comision",
    )
    session.add(org)
    session.commit()
    assert org.org_link == "www.congreso.gob.pe/comision"


def test_create_congresista(session):
    congresista = Congresista(
        full_name="Ana Maria Torres Torres",
        first_name="Ana Maria",
        last_name="Torres Torres",
        dni="12345678",
        photo_url="https://example.com/photo",
        website="https://example.com",
    )
    session.add(congresista)
    session.commit()
    assert congresista.first_name == "Ana Maria"
    assert congresista.dni == "12345678"


def test_create_bill(session):
    bill = Bill(
        id="B001",
        leg_period=LegPeriod.PERIODO_2021_2026,
        legislature=Legislature.LEGISLATURA_2021_1,
        presentation_date=datetime.now(),
        title="Ley de Transparencia",
        summary="Resumen de ley",
        observations="Observaciones aquí",
        complete_text="Texto completo",
        status="En trámite",
        proponent=Proponents.CONGRESO,
        author_id=1,
        bancada_id=10,
        approved=False,
    )
    session.add(bill)
    session.commit()
    assert bill.title == "Ley de Transparencia"


def test_create_vote_event_and_vote(session):
    vote_event = VoteEvent(
        leg_period=LegPeriod.PERIODO_2021_2026,
        bill_or_motion="Bill",
        bill_motion_id="B001",
        date=datetime.now(),
        result=VoteResult.APROBADO,
        majority_type=MajorityType.SIMPLE,
    )
    session.add(vote_event)
    vote = Vote(vote_event_id="VOT123", voter_id=1, option=VoteOption.SI, bancada_id=10)
    session.add(vote)
    session.commit()
    assert vote.option == VoteOption.SI


def test_attendance(session):
    attendance = Attendance(event_id=1, attendee_id=1, status=AttendanceStatus.PRESENTE)
    session.add(attendance)
    session.commit()
    assert attendance.status == AttendanceStatus.PRESENTE


def test_bill_step(session):
    step = BillStep(
        id=1,
        bill_id="B001",
        vote_step=True,
        vote_event_id=None,
        step_type=BillStepType.VOTACION,
        step_date=datetime.now(),
        step_detail="Votación en pleno",
    )
    session.add(step)
    session.commit()
    assert step.step_type == BillStepType.VOTACION


def test_membership_validation(session):
    membership = Membership(
        id=1,
        role=RoleOrganization.MIEMBRO,
        person_id=1,
        org_id=1,
        start_date=datetime.now() - timedelta(days=30),
        end_date=datetime.now(),
    )
    session.add(membership)
    session.commit()
    assert membership.role == RoleOrganization.MIEMBRO


def test_unique_vote_constraint(session):
    v1 = Vote(vote_event_id="VOT123", voter_id="1", option=VoteOption.NO, bancada_id=10)
    v2 = Vote(
        vote_event_id="VOT123", voter_id="1", option=VoteOption.SI, bancada_id=10
    )  # same unique key

    session.add_all([v1, v2])

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_bill_congresistas(session):
    relation = BillCongresistas(
        bill_id="B001", person_id=1, role_type=RoleTypeBill.COAUTHOR
    )
    session.add(relation)
    session.commit()
    assert relation.role_type == RoleTypeBill.COAUTHOR


def test_bill_committees(session):
    committee = Organization(
        leg_period=LegPeriod.PERIODO_2021_2026,
        leg_year=LegislativeYear.YEAR_2021_2022,
        org_name="Congreso del Perú",
        org_type=TypeOrganization.COMISON,
        comm_type=TypeCommittee.COM_ETICA,
        org_link="www.congreso.gob.pe/comision",
    )
    session.add(committee)
    session.commit()

    relation = BillCommittees(bill_id="B001", committee_id=committee.org_id)
    session.add(relation)
    session.commit()
    assert relation.committee_id == 1


def test_vote_counts(session):
    vote_count = VoteCounts(
        vote_event_id=1, option=VoteOption.SI, bancada_id=10, count=40
    )
    session.add(vote_count)
    session.commit()
    assert vote_count.count == 40
