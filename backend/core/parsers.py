from __future__ import annotations

import re
import unicodedata
from backend.core.constants import (
    BILL_ROLE_MAPS,
    LEG_PERIOD_ALIASES,
    LEGISLATURE_ALIASES,
)
from backend.core.enums import (
    BillStepType,
    LegPeriod,
    LegislativeYear,
    Legislature,
    MotionStepType,
    MotionType,
    Proponents,
    RoleOrganization,
    RoleTypeBill,
)


def _normalize_leg_period(value: str) -> str:
    # 1) Unicode normalize (handles odd forms)
    v = unicodedata.normalize("NFKC", value)

    # 2) Replace non-breaking spaces and other common weird spaces with normal space
    v = v.replace("\xa0", " ").replace("\u202f", " ").replace("\u2007", " ")

    v = v.strip()

    # 3) normalize different dash characters to "-"
    v = re.sub(r"[–—−]", "-", v)

    # 4) normalize spaces around dash
    v = re.sub(r"\s*-\s*", "-", v)

    # 5) collapse multiple spaces
    v = re.sub(r"\s+", " ", v)

    return v


LEG_PERIOD_RE = re.compile(r"(\d{4})-(\d{4})")


def parse_leg_period(value: str) -> LegPeriod:
    if value is None:
        raise ValueError("leg_period cannot be null")

    v = _normalize_leg_period(value)

    canon = LEG_PERIOD_ALIASES.get(v)
    if canon is None:
        m = LEG_PERIOD_RE.search(v)
        if m:
            canon = f"{m.group(1)}-{m.group(2)}"

    if canon is None:
        raise ValueError(f"Unknown leg period: {value!r} (normalized={v!r})")

    return LegPeriod(canon)


def _normalize_legislature(value: str) -> str:
    v = value.strip()
    v = re.sub(r"\s+", " ", v)  # collapse whitespace
    return v


def parse_legislature(value: str) -> Legislature:
    if value is None:
        raise ValueError("legislature cannot be null")

    v = _normalize_legislature(value)
    canon = LEGISLATURE_ALIASES.get(v)

    if canon is None:
        raise ValueError(f"Unknown legislature: {value!r}")

    return Legislature(canon)


def parse_role_bill(value: int | str) -> RoleTypeBill:
    if value is None:
        raise ValueError("role_bill cannot be null")

    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())

    canon = BILL_ROLE_MAPS.get(value, value)
    role_map = {
        "author": RoleTypeBill.AUTHOR,
        "autor": RoleTypeBill.AUTHOR,
        "coauthor": RoleTypeBill.COAUTHOR,
        "coautor": RoleTypeBill.COAUTHOR,
        "adherente": RoleTypeBill.ADHERENTE,
        RoleTypeBill.AUTHOR.value: RoleTypeBill.AUTHOR,
        RoleTypeBill.COAUTHOR.value: RoleTypeBill.COAUTHOR,
        RoleTypeBill.ADHERENTE.value: RoleTypeBill.ADHERENTE,
    }

    role = role_map.get(str(canon).strip().lower())
    if role is None:
        raise ValueError(f"Unknown role_bill: {value!r}")
    return role


def parse_motion_type(value: str) -> MotionType:
    if value is None:
        raise ValueError("motion_type cannot be null")

    v = " ".join(value.strip().split())

    # Direct match for scalar enum values.
    for item in MotionType:
        if isinstance(item.value, str) and item.value == v:
            return item

    # Handle the multi-value case for COMISION_INVESTIGADORA.
    if v in MotionType.COMISION_INVESTIGADORA.value:
        return MotionType.COMISION_INVESTIGADORA

    raise ValueError(f"Unknown motion_type: {value!r}")


def parse_proponent(value: str) -> Proponents:
    if value is None:
        raise ValueError("proponent cannot be null")

    v = " ".join(value.strip().split())

    try:
        return Proponents(v)
    except ValueError:
        pass

    # Handle suffixes like "Congreso-Actualización"
    if "-" in v:
        head = v.split("-", 1)[0].strip()
        try:
            return Proponents(head)
        except ValueError:
            pass

    raise ValueError(f"Unknown proponent: {value!r}")


DES_ESTADO_TO_MOTION_STEP_LABEL: dict[str, MotionStepType] = {
    "": MotionStepType.SIN_CATEGORIA,
    # Presented / admission
    "Presentado": MotionStepType.PRESENTADO,
    "Admitida la Moción": MotionStepType.ADMISION,
    "ADMITIDA A DEBATE": MotionStepType.ADMISION,
    "NO ADMITIDA A DEBATE": MotionStepType.ADMISION,
    "RECHAZADA LA ADMISIÓN A DEBATE": MotionStepType.ADMISION,
    # Committee handling
    "En Comisión": MotionStepType.ETAPA_EN_COMISION,
    "Integrantes de Comisión": MotionStepType.ETAPA_EN_COMISION,
    "Aprobado integrantes de Comisión": MotionStepType.ETAPA_EN_COMISION,
    # Agenda / internal routing (CD = Consejo Directivo)
    "En Agenda C.D": MotionStepType.AGENDA_CD,
    "PARA SER VISTA POR EL CONSEJO DIRECTIVO": MotionStepType.AGENDA_CD,
    "Tramitada con conocimiento del CD": MotionStepType.ACUERDO_CD,
    "TRAMITADA CON ACUERDO DE CD": MotionStepType.ACUERDO_CD,
    "Por Acuerdo de CD.": MotionStepType.ACUERDO_CD,
    "Acuerdo Junta de Portavoces": MotionStepType.ACUERDO_JP,
    # Pleno routing / agenda
    "Para ser vista por el Pleno": MotionStepType.AGENDA_DEL_PLENO,
    "En Agenda del Pleno": MotionStepType.AGENDA_DEL_PLENO,
    "En Agenda de Pleno": MotionStepType.AGENDA_DEL_PLENO,
    "Orden del Día": MotionStepType.AGENDA_DEL_PLENO,
    "Dado cuenta en el Pleno": MotionStepType.ANUNCIO_O_DACION_DE_CUENTA,
    "Se ha dado cuenta": MotionStepType.ANUNCIO_O_DACION_DE_CUENTA,
    "Por Acuerdo de Pleno": MotionStepType.ANUNCIO_O_DACION_DE_CUENTA,
    # Debate / floor handling
    "En Debate": MotionStepType.DEBATE,
    "En debate": MotionStepType.DEBATE,
    "Leída en sesión": MotionStepType.DEBATE,
    "Fundamentada la Moción": MotionStepType.FUNDAMENTACION,
    # Vote-ish / outcomes
    "Aprobada": MotionStepType.VOTACION_O_DECISION,
    "Aprobada la Moción": MotionStepType.VOTACION_O_DECISION,
    "Rechazada": MotionStepType.VOTACION_O_DECISION,
    # Reconsideration
    "Reconsideración": MotionStepType.RECONSIDERACION,
    "Rechazada Reconsideración": MotionStepType.RECONSIDERACION,
    # Text updates
    "Texto consensuado": MotionStepType.REVISION_DE_TEXTO,
    "Texto Sustitutorio": MotionStepType.REVISION_DE_TEXTO,
    "Adhesión": MotionStepType.REVISION_DE_TEXTO,
    "Se adhiere": MotionStepType.REVISION_DE_TEXTO,
    "Retiro de Firma": MotionStepType.RETIRADO,
    # Official comms / documents
    "Oficio": MotionStepType.COMUNICACION_OFICIAL,
    "Fe de Erratas": MotionStepType.FE_DE_ERRATAS_O_CORRECCION,
    # Publication
    "Publicado Diario Oficial  El Peruano": MotionStepType.PUBLICADO,
    "Publicado Diario Oficial El Peruano": MotionStepType.PUBLICADO,
    # Appearances (minister, etc.)
    "Concurre Ministro": MotionStepType.ASISTENCIA_O_COMPARECENCIA,
    "Asiste": MotionStepType.ASISTENCIA_O_COMPARECENCIA,
    "Asistió el Ministro  para contestar el pliego.": MotionStepType.ASISTENCIA_O_COMPARECENCIA,
    "Asistió el Ministro para contestar el pliego.": MotionStepType.ASISTENCIA_O_COMPARECENCIA,
    # Order / procedural
    "Cuestión de Orden": MotionStepType.CUESTION_DE_ORDEN,
    "EN CUARTO INTERMEDIO": MotionStepType.CUARTO_INTERMEDIO,
    # Requirements / blocking status
    "INCUMPLE REQUISITOS PARA CONTINUAR SU TRÁMITE": MotionStepType.BLOQUEO_POR_REQUISITOS,
    # Withdrawal
    "Solicita retiro de moción": MotionStepType.RETIRADO,
    "RETIRADA POR SU AUTOR": MotionStepType.RETIRADO,
    "Se deje sin efecto": MotionStepType.RETIRADO,
    # Archive
    "Al archivo": MotionStepType.ARCHIVADO,
    "En Archivo General": MotionStepType.ARCHIVADO,
    # Resignation / referrals
    "Renuncia": MotionStepType.RENUNCIA,
    "En Fiscalía de la Nación": MotionStepType.COMUNICACION_OFICIAL,
}


DES_ESTADO_TO_STEP_LABEL: dict[str, BillStepType] = {
    "------": BillStepType.SIN_CATEGORIA,
    # Presented
    "PRESENTADO": BillStepType.PRESENTADO,
    # Assigned / committee routing
    "EN COMISIÓN": BillStepType.EN_COMISION,
    "PASA A COMISIÓN": BillStepType.EN_COMISION,
    "RETORNA A COMISIÓN": BillStepType.EN_COMISION,
    "Acumulado en Sala": BillStepType.ACUMULADO,
    # Committee stage artifacts / decisions
    "DICTAMEN": BillStepType.DICTAMEN_O_ACUERDO_DE_COMISION,
    "ACUERDO DE COMISIÓN": BillStepType.DICTAMEN_O_ACUERDO_DE_COMISION,
    # Exemptions / procedural shortcuts
    "Dispensado de Dictamen": BillStepType.EXONERACION_DE_DICTAMEN,
    "EXONERADO DE DICTAMEN": BillStepType.EXONERACION_DE_DICTAMEN,
    "EXONERADO DE PLAZO DE PUBLICACIÓN": BillStepType.EXONERACION_DE_DICTAMEN,
    "Dispensado de Publicación en el Portal": BillStepType.EXONERACION_DE_DICTAMEN,
    # Agenda
    "Orden del Día": BillStepType.AGENDA_DEL_PLENO,
    "EN AGENDA DEL PLENO": BillStepType.AGENDA_DEL_PLENO,
    "EN AGENDA DE LA COMISIÓN PERMANENTE": BillStepType.AGENDA_DE_LA_COMISION_PERMANENTE,
    # Debate
    "EN DEBATE - PLENO": BillStepType.DEBATE_EN_EL_PLENO,
    "EN DEBATE - COMISIÓN PERMANENTE": BillStepType.DEBATE_EN_LA_COMISION_PERMANENTE,
    "EN DEBATE DE LA COMISIÓN PERMANENTE": BillStepType.DEBATE_EN_LA_COMISION_PERMANENTE,
    # Vote events
    "APROBADO 1ERA. VOTACIÓN": BillStepType.VOTACION,
    "Pendiente 2da. votación": BillStepType.VOTACION,
    "Pendiente 2da. Votación": BillStepType.VOTACION,
    "No alcanzó Nº de votos": BillStepType.VOTACION,
    "No alcanzó N° de votos": BillStepType.VOTACION,
    "No alcanzó No de votos": BillStepType.VOTACION,
    "NO APROBADO": BillStepType.VOTACION,
    "APROBADO": BillStepType.VOTACION,
    "Aprobado Com.Permanente": BillStepType.VOTACION,
    "ACUERDO DEL PLENO": BillStepType.VOTACION,
    # Text / autographs (post-approval drafting)
    "TEXTO SUSTITUTORIO": BillStepType.TEXTO_SUSTITUTORIO_O_REVISION,
    "AUTÓGRAFA": BillStepType.AUTOGRAFA,
    "AUTÓGRAFA OBSERVADA": BillStepType.AUTOGRAFA,
    # Reconsideration
    "EN RECONSIDERACIÓN": BillStepType.RECONSIDERACION,
    # Rejection
    "RECHAZADO": BillStepType.RECHAZADO,
    # Withdrawal
    "Retirado por su Autor": BillStepType.RETIRADO,
    "Solicita Retiro": BillStepType.RETIRADO,
    "Retiro de Firma": BillStepType.RETIRADO,
    # Archive
    "Al Archivo": BillStepType.ARCHIVADO,
    "DECRETO DE ARCHIVO": BillStepType.ARCHIVADO,
    # Promulgation / publication
    "Promulgado/Presidente de la República": BillStepType.PROMULGADO,
    "Promulgado/Presidente del Congreso": BillStepType.PROMULGADO,
    "Publicada en el Diario Oficial El Peruano": BillStepType.PUBLICADO,
    # Clarification / internal routing
    "ACLARACIÓN": BillStepType.ACLARACION,
    "EN CUARTO INTERMEDIO": BillStepType.CUARTO_INTERMEDIO,
    "PARA CONSEJO DIRECTIVO": BillStepType.AGENDA_DEL_CONSEJO_DIRECTIVO,
}


def classify_motion_des_estado(
    des_estado: str | None, detail: str | None = None
) -> MotionStepType:
    key = _normalize_step_text(des_estado)
    status_label = _lookup_step_label(DES_ESTADO_TO_MOTION_STEP_LABEL, key)
    detail_labels = _collect_detail_labels(detail, _MOTION_DETAIL_LABEL_RULES)
    return _resolve_step_label(
        status_label,
        detail_labels,
        _MOTION_STEP_PRIORITY,
        MotionStepType.SIN_CATEGORIA,
    )


def classify_des_estado(
    des_estado: str | None, detail: str | None = None
) -> BillStepType:
    key = _normalize_step_text(des_estado)
    status_label = _lookup_step_label(DES_ESTADO_TO_STEP_LABEL, key)
    detail_labels = _collect_detail_labels(detail, _BILL_DETAIL_LABEL_RULES)
    return _resolve_step_label(
        status_label,
        detail_labels,
        _BILL_STEP_PRIORITY,
        BillStepType.SIN_CATEGORIA,
    )


def _normalize_step_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\xa0", " ").replace("\u202f", " ").replace("\u2007", " ")
    text = re.sub(r"[–—−]", "-", text)
    return " ".join(text.strip().split())


def _lookup_step_label(mapping: dict[str, object], key: str):
    if not key:
        return None
    return mapping.get(key) or mapping.get(key.upper()) or mapping.get(key.title())


def _collect_detail_labels(
    detail: str | None, rules: list[tuple[re.Pattern[str], object]]
) -> list:
    detail_key = _normalize_step_text(detail)
    if not detail_key:
        return []

    labels = []
    for pattern, label in rules:
        if pattern.search(detail_key):
            labels.append(label)
    return labels


def _resolve_step_label(
    status_label, detail_labels: list, priority_map: dict, unknown_label
):
    best_label = status_label or unknown_label
    best_rank = (priority_map.get(best_label, 0), 0, 0)

    for index, label in enumerate(detail_labels):
        rank = (priority_map.get(label, 0), 1, -index)
        if rank > best_rank:
            best_label = label
            best_rank = rank

    return best_label


_BILL_DETAIL_LABEL_RULES: list[tuple[re.Pattern[str], BillStepType]] = [
    (
        re.compile(
            r"\bpublicad[ao]s?\b.*\b(diario oficial|el peruano)\b", re.IGNORECASE
        ),
        BillStepType.PUBLICADO,
    ),
    (
        re.compile(r"\bpromulgad[ao]s?\b", re.IGNORECASE),
        BillStepType.PROMULGADO,
    ),
    (
        re.compile(
            r"\bsolicita retiro\b|\bretirad[oa] por su autor\b|\bretiro de firma\b|\bconsid[eé]rese retirad[oa]\b",
            re.IGNORECASE,
        ),
        BillStepType.RETIRADO,
    ),
    (
        re.compile(
            r"\bal archivo\b|\benv[ií]o al archivo\b|\bdecreto de archivo\b|\bpas[oó] al archivo\b",
            re.IGNORECASE,
        ),
        BillStepType.ARCHIVADO,
    ),
    (
        re.compile(
            r"\basistencia y votaci[oó]n\b|\bprimera votaci[oó]n\b|\bsegunda votaci[oó]n\b|\b1era\.?\s*votaci[oó]n\b|\b2da\.?\s*votaci[oó]n\b|\bno alcanz[oó]\b.*\bvotos?\b",
            re.IGNORECASE,
        ),
        BillStepType.VOTACION,
    ),
    (
        re.compile(r"\bcuarto intermedio\b", re.IGNORECASE),
        BillStepType.CUARTO_INTERMEDIO,
    ),
    (
        re.compile(r"\bdebat\w+\b.*\bcomisi[oó]n permanente\b", re.IGNORECASE),
        BillStepType.DEBATE_EN_LA_COMISION_PERMANENTE,
    ),
    (
        re.compile(r"\b(debate|debat\w+)\b", re.IGNORECASE),
        BillStepType.DEBATE_EN_EL_PLENO,
    ),
    (
        re.compile(
            r"^reconsideraci[oó]n\b|\basistencia y votaci[oó]n\s*-\s*reconsideraci[oó]n\b|\breconsideraci[oó]n a la votaci[oó]n\b|\bpresentaron reconsideraci[oó]n\b|\bpresentada .* reconsideraci[oó]n\b",
            re.IGNORECASE,
        ),
        BillStepType.RECONSIDERACION,
    ),
    (
        re.compile(
            r"\b(texto|nuevo texto|f[oó]rmula)\s+sustitutor\w*\b|\btexto consensuado\b",
            re.IGNORECASE,
        ),
        BillStepType.TEXTO_SUSTITUTORIO_O_REVISION,
    ),
    (
        re.compile(r"\baut[oó]grafa\b", re.IGNORECASE),
        BillStepType.AUTOGRAFA,
    ),
    (
        re.compile(r"\baclaraci[oó]n\b", re.IGNORECASE),
        BillStepType.ACLARACION,
    ),
    (
        re.compile(
            r"\bexoneraci[oó]n de dictamen\b|\bexoneraci[oó]n del? plazo de publicaci[oó]n\b|\bdispensad[oa] de dictamen\b|\bdispensad[oa] de publicaci[oó]n\b|\bexoneraci[oó]n del tr[aá]mite de env[ií]o a comisi[oó]n\b",
            re.IGNORECASE,
        ),
        BillStepType.EXONERACION_DE_DICTAMEN,
    ),
    (
        re.compile(r"\bacumulad[oa]\b", re.IGNORECASE),
        BillStepType.ACUMULADO,
    ),
    (
        re.compile(
            r"\b(pasa|pas[oó]|retorna|retorn[ao]) a comisi[oó]n\b|\bdevuelv\w+ a la comisi[oó]n\b",
            re.IGNORECASE,
        ),
        BillStepType.EN_COMISION,
    ),
    (
        re.compile(r"\bconsejo directivo\b", re.IGNORECASE),
        BillStepType.AGENDA_DEL_CONSEJO_DIRECTIVO,
    ),
    (
        re.compile(r"\bagenda\b.*\bcomisi[oó]n permanente\b", re.IGNORECASE),
        BillStepType.AGENDA_DE_LA_COMISION_PERMANENTE,
    ),
    (
        re.compile(
            r"\b(orden del d[ií]a|ampliaci[oó]n de agenda|agenda del pleno)\b",
            re.IGNORECASE,
        ),
        BillStepType.AGENDA_DEL_PLENO,
    ),
]


_BILL_STEP_PRIORITY: dict[BillStepType, int] = {
    BillStepType.SIN_CATEGORIA: 0,
    BillStepType.AGENDA_DEL_CONSEJO_DIRECTIVO: 100,
    BillStepType.AGENDA_DEL_PLENO: 110,
    BillStepType.AGENDA_DE_LA_COMISION_PERMANENTE: 120,
    BillStepType.EN_COMISION: 130,
    BillStepType.PRESENTADO: 140,
    BillStepType.DICTAMEN_O_ACUERDO_DE_COMISION: 160,
    BillStepType.EXONERACION_DE_DICTAMEN: 320,
    BillStepType.ACUMULADO: 330,
    BillStepType.ACLARACION: 340,
    BillStepType.TEXTO_SUSTITUTORIO_O_REVISION: 350,
    BillStepType.AUTOGRAFA: 360,
    BillStepType.RECONSIDERACION: 370,
    BillStepType.DEBATE_EN_EL_PLENO: 500,
    BillStepType.DEBATE_EN_LA_COMISION_PERMANENTE: 510,
    BillStepType.CUARTO_INTERMEDIO: 520,
    BillStepType.VOTACION: 530,
    BillStepType.RECHAZADO: 540,
    BillStepType.ARCHIVADO: 550,
    BillStepType.RETIRADO: 560,
    BillStepType.PROMULGADO: 570,
    BillStepType.PUBLICADO: 580,
}


_MOTION_DETAIL_LABEL_RULES: list[tuple[re.Pattern[str], MotionStepType]] = [
    (
        re.compile(r"\bfundamenta\b.*\bmoci[oó]n\b", re.IGNORECASE),
        MotionStepType.FUNDAMENTACION,
    ),
    (
        re.compile(
            r"\basistencia y votaci[oó]n\b|\b(fue|fueron)\s+aprobad[ao]s?\b|\b(fue|fueron)\s+rechazad[ao]s?\b|\baprobad[ao]\s+(la|el|un|una)\b|\brechazad[ao]\s+la\b|\bno alcanz[oó]\b.*\bvotos?\b|\bpor \d+ votos?\b",
            re.IGNORECASE,
        ),
        MotionStepType.VOTACION_O_DECISION,
    ),
    (
        re.compile(
            r"\badmitid[ao]\b.*\bmoci[oó]n\b|\badmisi[oó]n a debate\b", re.IGNORECASE
        ),
        MotionStepType.ADMISION,
    ),
    (
        re.compile(
            r"\bse ha dado cuenta\b|\bse consultar[aá] su admisi[oó]n\b|\banunci[oó] que se hab[ií]a presentado la moci[oó]n\b",
            re.IGNORECASE,
        ),
        MotionStepType.ANUNCIO_O_DACION_DE_CUENTA,
    ),
    (
        re.compile(
            r"\ble[ií]d[ao] en sesi[oó]n\b|\bfue le[ií]d[ao]\b.*\bsesi[oó]n\b|\bse reabri[oó] el debate\b|\breabri[oó] el debate\b|\ben debate\b",
            re.IGNORECASE,
        ),
        MotionStepType.DEBATE,
    ),
    (
        re.compile(
            r"\bpas[oó] a la comisi[oó]n\b|\bpase a la comisi[oó]n\b|\bdevolvi[oó] a la comisi[oó]n\b",
            re.IGNORECASE,
        ),
        MotionStepType.ETAPA_EN_COMISION,
    ),
    (
        re.compile(
            r"^(acta de acuerdo|acuerdo n[°ºo.]?\s*\d+|oficio|carta|informe)\b|^\bn[°ºo.]?\s*\d+",
            re.IGNORECASE,
        ),
        MotionStepType.COMUNICACION_OFICIAL,
    ),
    (
        re.compile(
            r"\bsolicita el retiro\b|\bsolicita retiro\b|\bconsid[eé]rese retirad[oa]\b|\bretira su moci[oó]n\b|\bdeje sin efecto\b|\bsolicita el retiro de la moci[oó]n\b",
            re.IGNORECASE,
        ),
        MotionStepType.RETIRADO,
    ),
    (
        re.compile(r"\bal archivo\b|\bpas[oó] al archivo\b", re.IGNORECASE),
        MotionStepType.ARCHIVADO,
    ),
    (
        re.compile(
            r"\bcuarto intermedio\b|\btexto sustitutorio presentado\b", re.IGNORECASE
        ),
        MotionStepType.CUARTO_INTERMEDIO,
    ),
    (
        re.compile(r"\breconsideraci[oó]n\b", re.IGNORECASE),
        MotionStepType.RECONSIDERACION,
    ),
    (
        re.compile(
            r"\btexto sustitutorio\b|\btexto consensuado\b|\badhier[ea]\b|\bcon texto sustitutorio\b",
            re.IGNORECASE,
        ),
        MotionStepType.REVISION_DE_TEXTO,
    ),
    (
        re.compile(r"\bfe de erratas\b", re.IGNORECASE),
        MotionStepType.FE_DE_ERRATAS_O_CORRECCION,
    ),
    (
        re.compile(
            r"^(censurar|saludar|felicitar|expresar|considerar|conformar|aprobar|declarar|otorgar|constituir|crear)\b",
            re.IGNORECASE,
        ),
        MotionStepType.PRESENTADO,
    ),
]


_MOTION_STEP_PRIORITY: dict[MotionStepType, int] = {
    MotionStepType.SIN_CATEGORIA: 0,
    MotionStepType.AGENDA_CD: 100,
    MotionStepType.ACUERDO_CD: 105,
    MotionStepType.ACUERDO_JP: 108,
    MotionStepType.AGENDA_DEL_PLENO: 110,
    MotionStepType.PRESENTADO: 120,
    MotionStepType.REVISION_DE_TEXTO: 300,
    MotionStepType.RECONSIDERACION: 310,
    MotionStepType.COMUNICACION_OFICIAL: 320,
    MotionStepType.ETAPA_EN_COMISION: 330,
    MotionStepType.ASISTENCIA_O_COMPARECENCIA: 340,
    MotionStepType.ANUNCIO_O_DACION_DE_CUENTA: 350,
    MotionStepType.ADMISION: 360,
    MotionStepType.FUNDAMENTACION: 370,
    MotionStepType.DEBATE: 380,
    MotionStepType.CUESTION_DE_ORDEN: 390,
    MotionStepType.CUARTO_INTERMEDIO: 400,
    MotionStepType.VOTACION_O_DECISION: 410,
    MotionStepType.RETIRADO: 420,
    MotionStepType.ARCHIVADO: 430,
    MotionStepType.BLOQUEO_POR_REQUISITOS: 440,
    MotionStepType.RENUNCIA: 450,
    MotionStepType.PUBLICADO: 460,
    MotionStepType.FE_DE_ERRATAS_O_CORRECCION: 470,
}


def find_leg_period(leg_year: LegislativeYear):
    int_year = int(leg_year)

    if int_year in range(2026, 2031):
        return parse_leg_period("Parlamentario 2026 - 2031")
    if int_year in range(2021, 2026):
        return parse_leg_period("Parlamentario 2021 - 2026")
    if int_year in range(2016, 2021):
        return parse_leg_period("Parlamentario 2016 - 2021")
    if int_year in range(2011, 2016):
        return parse_leg_period("Parlamentario 2011 - 2016")
    if int_year in range(2006, 2011):
        return parse_leg_period("Parlamentario 2006 - 2011")
    if int_year in range(2001, 2006):
        return parse_leg_period("Parlamentario 2001 - 2006")
    if int_year in range(2000, 2001):
        return parse_leg_period("Parlamentario 2000 - 2001")
    if int_year in range(1995, 2000):
        return parse_leg_period("Parlamentario 1995 - 2000")
    return parse_leg_period("CCD 1992 -1995")


def normalize_membership_role(raw: str) -> RoleOrganization:
    if not raw:
        raise ValueError("Empty membership role")

    role = raw.strip().lower()

    role_map = {
        "presidenta": RoleOrganization.PRESIDENTE,
        "presidente": RoleOrganization.PRESIDENTE,
        "vicepresidenta": RoleOrganization.VICEPRESIDENTE,
        "vicepresidente": RoleOrganization.VICEPRESIDENTE,
        "secretaria": RoleOrganization.SECRETARIO,
        "secretario": RoleOrganization.SECRETARIO,
        "vocera": RoleOrganization.VOCERO,
        "vocero": RoleOrganization.VOCERO,
        "miembro": RoleOrganization.MIEMBRO,
        "titular": RoleOrganization.TITULAR,
        "suplente": RoleOrganization.SUPLENTE,
        "accesitaria": RoleOrganization.ACCESITARIO,
        "accesitario": RoleOrganization.ACCESITARIO,
        "presidente (e) del congreso de la república": RoleOrganization.PRESIDENTE,
        "segundo vicepresidente": RoleOrganization.SEGUNDO_VICE,
        "tercer vicepresidente": RoleOrganization.TERCER_VICE,
    }

    normalized_role = role_map.get(role)
    if normalized_role is None:
        raise ValueError(f"Unknown role: {role!r}")

    return normalized_role


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\xa0", " ").replace("\u202f", " ").replace("\u2007", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


# Canonical outputs must exactly match your enum values
_COMM_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    # Most specific first
    (
        re.compile(r"^sub\s*comisi[oó]n\s+de\s+acusaciones\s+constitucionales", re.I),
        "Subcomisión de Acusaciones Constitucionales",
    ),
    (
        re.compile(r"^sub\s*comisi[oó]n\s+de\s+control\s+pol[ií]tico", re.I),
        "Subcomisión de Control Político",
    ),
    (
        re.compile(
            r"^comisi[oó]n\s+de\s+levantamiento\s+de\s+inmunidad\s+parlamentaria", re.I
        ),
        "Comisión de Levantamiento de Inmunidad Parlamentaria",
    ),
    (
        re.compile(r"^comisi[oó]n\s+de\s+[eé]tica\s+parlamentaria", re.I),
        "Comisión de Ética Parlamentaria",
    ),
    (
        re.compile(r"^sub\s*comisi[oó]n\s+de\s+seguimiento\s+del\s+tlc", re.I),
        "Sub Comisión de Seguimiento del TLC",
    ),
    # Common noisy cases
    (re.compile(r"^comisi[oó]n\s+ordinaria\b", re.I), "Comisión Ordinaria"),
    (
        re.compile(r"^comisiones?\s+investigadoras?\b", re.I),
        "Comisiones Investigadoras",
    ),
    (re.compile(r"^comisiones?\s+especiales?\b", re.I), "Comisiones Especiales"),
    (re.compile(r"^grupo\s+de\s+trabajo\b", re.I), "Grupo de Trabajo"),
]


def parse_comm_type(value: str) -> str:
    raw = value
    v = _norm_text(value)

    # normalize dash variants (optional, but consistent with your style)
    v = re.sub(r"[–—−]", "-", v)

    for pat, canon in _COMM_TYPE_RULES:
        if pat.search(v):
            return canon

    raise ValueError(f"Unknown comm_type: {raw!r} (normalized={v!r})")
