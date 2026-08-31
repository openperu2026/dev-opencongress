from marshmallow import Schema, fields, validate


class ErrorDetailSchema(Schema):
    code = fields.String(required=True)
    message = fields.String(required=True)


class ErrorResponseSchema(Schema):
    error = fields.Nested(ErrorDetailSchema, required=True)


class HealthResponseSchema(Schema):
    status = fields.String(required=True)
    version = fields.String(required=True)


class PaginationQuerySchema(Schema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=50, validate=validate.Range(min=1, max=100))


class PaginationMetaSchema(Schema):
    page = fields.Integer(required=True)
    per_page = fields.Integer(required=True)
    total = fields.Integer(required=True)
    pages = fields.Integer(required=True)


class BillListQuerySchema(PaginationQuerySchema):
    title = fields.String(load_default=None)
    author = fields.String(load_default=None)
    author_id = fields.Integer(load_default=None)
    status = fields.String(load_default=None)
    pley_id = fields.String(load_default=None)
    law_id = fields.String(load_default=None)
    current_step = fields.String(load_default=None)
    presentation_date_from = fields.Date(load_default=None)
    presentation_date_to = fields.Date(load_default=None)
    organization = fields.String(load_default=None)


# Schema for the queries of bills, defining the type of data


class BillListItemSchema(Schema):
    id = fields.String(required=True)
    pley_id = fields.String(allow_none=True)
    title = fields.String(required=True)
    status = fields.String(required=True)
    proponent = fields.String(allow_none=True)
    author_id = fields.Integer(allow_none=True)
    author_name = fields.String(allow_none=True)
    presentation_date = fields.Date(allow_none=True)
    approved = fields.Boolean(required=True)


class BillListResponseSchema(Schema):
    items = fields.List(fields.Nested(BillListItemSchema), required=True)
    pagination = fields.Nested(PaginationMetaSchema, required=True)


class BillAuthorSchema(Schema):
    full_name = fields.String(required=True)
    id = fields.Integer(required=True)
    last_name = fields.String(allow_none=True)
    first_name = fields.String(allow_none=True)


class BillStepSchema(Schema):
    step_id = fields.Integer(required=True)
    step_type = fields.String(required=True)
    vote_step = fields.Boolean(required=True)
    step_date = fields.Date(required=True)
    step_detail = fields.String(required=True)


class BillDetailResponseSchema(Schema):
    id = fields.String(required=True)
    pley_id = fields.String(required=True)
    ley_id = fields.String(allow_none=True)
    title = fields.String(required=True)
    summary_congreso = fields.String(required=True)
    proponent = fields.String(required=True)
    status = fields.String(required=True)
    approval_status = fields.String(required=True)
    approved = fields.Boolean(required=True)
    days_since_presentation = fields.Integer(allow_none=True)
    observations = fields.String(required=True)
    author = fields.Nested(BillAuthorSchema, allow_none=True)
    party = fields.String(allow_none=True)
    presentation_date = fields.Date(allow_none=True)
    latest_step = fields.Nested(BillStepSchema, allow_none=True)
    topics = fields.List(fields.String(), required=True)
    bill_steps = fields.List(fields.Nested(BillStepSchema), required=True)


class CongressMemberListQuerySchema(PaginationQuerySchema):
    name = fields.String(load_default=None)
    party = fields.String(load_default=None)
    region = fields.String(load_default=None)
    condition = fields.String(load_default=None)
    committee = fields.String(load_default=None)
    special_committee = fields.String(load_default=None)


class CongressMemberMetricsSchema(Schema):
    proyectos_de_ley_presentados = fields.Integer(required=True)
    tasa_de_aprobacion_de_proyectos = fields.Float(allow_none=True)


class CongressMemberListItemSchema(Schema):
    id = fields.Integer(required=True)
    full_name = fields.String(required=True)
    first_name = fields.String(allow_none=True)
    last_name = fields.String(allow_none=True)
    photo_url = fields.String(allow_none=True)
    website = fields.String(allow_none=True)
    party_name = fields.String(allow_none=True)
    region = fields.String(allow_none=True)
    condition = fields.String(allow_none=True)
    votes_in_election = fields.Integer(allow_none=True)
    metrics = fields.Nested(CongressMemberMetricsSchema, allow_none=True)


class CongressMemberListResponseSchema(Schema):
    items = fields.List(fields.Nested(CongressMemberListItemSchema), required=True)
    pagination = fields.Nested(PaginationMetaSchema, required=True)
