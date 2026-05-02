from lxml.html import fromstring
from backend import RoleOrganization, find_leg_period
from backend.database.raw_models import RawBancada
from backend.process.schema import Organization, Membership
from backend.process.utils import get_current_leg_year, split_and_sort_name

CONGRESO_BASE_URL = "https://www.congreso.gob.pe"
LEGACY_CONGRESO_BASE_URL = "https://www3.congreso.gob.pe"


def process_bancada(
    raw_bancada: RawBancada,
) -> tuple[list[Organization], list[Membership]]:
    """
    Process a RawBancada instance into a Organization instance and a list of Memberships
    that maps all the congresistas who belongs to the Organization at a specific legislative year

    Args:
        raw_bancada (RawBancada): RawBancada instance that contains all the bancadas and membership for a specific period

    Returns:
        tuple[Organization, list[Membership]]: Organization instance and the list of Memberships
    """

    html = fromstring(raw_bancada.raw_html)

    rows = html.xpath('//*[@class="table-cng"]/tbody/tr')
    leg_year = get_current_leg_year(str(raw_bancada.timestamp))
    current_leg_period = find_leg_period(leg_year)

    membership_list = []
    bancadas_lst = []
    for row in rows:
        childs = row.getchildren()
        if len(childs) == 1:
            # Bancada
            bancada = childs[0].xpath(".//h2")[0].text_content().title()
            bancadas_lst.append(
                Organization(
                    org_name=bancada,
                    org_type="Bancada",
                    # TODO: Update this when the new congress website address
                    # for different routes for committees in camara
                    parent_org_name="Cámara de Diputados",
                    parent_org_type="Cámara",
                )
            )

        else:
            # Congresista
            name = row.xpath('.//*[@class="conginfo"]')[0].text
            full_name, _, _ = split_and_sort_name(name)

            membership_list.append(
                Membership(
                    cong_name=full_name,
                    org_name=bancada,
                    org_type="Bancada",
                    leg_period=current_leg_period,
                    role=RoleOrganization.MIEMBRO,
                    time_stamp=raw_bancada.timestamp,
                )
            )

    return bancadas_lst, membership_list
