import json
from rdflib import Graph, Namespace, RDF, Literal, URIRef

EX = Namespace("http://example.org/")
g = Graph()
g.bind("ex", EX)

BASE = "http://example.org/"
NS = Namespace(BASE)        # instances (students, courses, departments...)
EX = Namespace(BASE + "#")  # ontology (classes, properties)



def uri(template, data):
    try:
        return URIRef(BASE + template.format(**data))
    except KeyError:
        return None


def lit(value):
    return Literal(value) if value is not None else None

# =========================================================
# HELPERS
# =========================================================

def inst(template, data):
    """Create instance URIs (http://example.org/...)"""
    try:
        return URIRef(NS[template.format(**data)])
    except KeyError:
        return None


INTENT_MAP = {

    # 1
    "IdentifyIncidentImpact": {
        "subject": lambda d: inst("managed_element_{entity_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.ManagedElement),
            lambda s, d: (inst("trouble_ticket_{trouble_ticket_id}", d), EX.eventRelatedElement, s)
        ]
    },

    # 2
    "FindSharedAssets": {
        "subject": lambda d: inst("resource_{resource_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Resource),
            lambda s, d: (s, EX.label, lit(d.get("resource_label"))),
            lambda s, d: (s, EX.subSystemOf, inst("service_{service_id}", d))
        ]
    },

    # 3
    "GetResourceLogs": {
        "subject": lambda d: inst("log_{log_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.EventRecord),
            lambda s, d: (s, EX.logOriginatingManagedObject, inst("resource_{resource_id}", d)),
            lambda s, d: (s, EX.loggingTime, lit(d.get("log_time"))),
            lambda s, d: (s, EX.logText, lit(d.get("log_message")))
        ]
    },

    # 4
    "GetResourceMetrics": {
        "subject": lambda d: inst("metric_{metric_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Metric),
            lambda s, d: (s, EX.metricName, lit(d.get("metric_name"))),
            lambda s, d: (s, EX.metricValue, lit(d.get("metric_value"))),
            lambda s, d: (inst("resource_{resource_id}", d), EX.structuralElementObservable, s)
        ]
    },

    # 5
    "FindCorrelatedEvents": {
        "subject": lambda d: inst("event_{corr_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.EventRecord),
            lambda s, d: (s, EX.loggingTime, lit(d.get("log_time"))),
            lambda s, d: (s, EX.logText, lit(d.get("log_message"))),
            lambda s, d: (inst("event_{event_id}", d), EX.relation, s)
        ]
    },

    # 6
    "IdentifyEventSource": {
        "subject": lambda d: inst("agent_{originator_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Agent),
            lambda s, d: (s, EX.role, lit(d.get("originator_role"))),
            lambda s, d: (inst("event_{event_id}", d), EX.logOriginatingAgent, s)
        ]
    },

    # 7
    "DetectAlarmPatterns": {
        "subject": lambda d: inst("pattern_{pattern_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.AnomalyPattern),
            lambda s, d: (s, EX.label, lit(d.get("description"))),
            lambda s, d: (inst("event_{event_id}", d), EX.conformsTo, s)
        ]
    },

    # 8
    "FindCausalInterventions": {
        "subject": lambda d: inst("change_{change_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Change),
            lambda s, d: (s, EX.description, lit(d.get("change_description"))),
            lambda s, d: (s, EX.changeRequestActualStartTime, lit(d.get("start_time"))),
            lambda s, d: (s, EX.changeRequestImpact, inst("resource_{resource_id}", d)),
            lambda s, d: (s, EX.correlatedNotifications, inst("event_{event_id}", d))
        ]
    },

    # 9
    "IdentifyRootCause": {
        "subject": lambda d: inst("trouble_ticket_{trouble_ticket_id}", d),
        "triples": [
            lambda s, d: (s, EX.problemCategory, lit(d.get("category_name"))),
            lambda s, d: (s, EX.problemResponsibility, lit(d.get("responsibility")))
        ]
    },

    # 10
    "GetIncidentSequence": {
        "subject": lambda d: inst("event_{event_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.EventRecord),
            lambda s, d: (s, EX.loggingTime, lit(d.get("timestamp"))),
            lambda s, d: (inst("trouble_ticket_{trouble_ticket_id}", d), EX.relation, s)
        ]
    },

    # 11
    "MapEventsToResources": {
        "subject": lambda d: inst("event_{event_id}", d),
        "triples": [
            lambda s, d: (s, EX.logOriginatingManagedObject, inst("resource_{resource_id}", d))
        ]
    },

    # 12
    "FindSimilarIncidents": {
        "subject": lambda d: inst("trouble_ticket_{similar_ticket_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.TroubleTicket),
            lambda s, d: (s, EX.problemCategory, lit(d.get("ticket_category")))
        ]
    },

    # 13
    "SuggestOperationPlan": {
        "subject": lambda d: inst("plan_{plan_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.OperationPlan),
            lambda s, d: (s, EX.description, lit(d.get("plan_description"))),
            lambda s, d: (s, EX.operationPlanPostCondition, lit(d.get("plan_outcome"))),
            lambda s, d: (inst("event_{event_id}", d), EX.alarmProposedReapairAction, s)
        ]
    },

    # 14
    "SummarizeCorrectiveActions": {
        "subject": lambda d: inst("action_{action_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.ProcedureExecution),
            lambda s, d: (inst("agent_{agent_id}", d), RDF.type, EX.Agent),
            lambda s, d: (s, EX.description, lit(d.get("action_description"))),
            lambda s, d: (inst("trouble_ticket_{trouble_ticket_id}", d), EX.hasPart, s),
            lambda s, d: (s, EX.madeBy, inst("agent_{agent_id}", d)),
            lambda s, d: (inst("agent_{agent_id}", d), EX.label, lit(d.get("agent_label")))
        ]
    },

    # 15
    "IdentifyResolvingActions": {
        "subject": lambda d: inst("action_{action_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.ProcedureExecution),
            lambda s, d: (s, EX.description, lit(d.get("action_description"))),
            lambda s, d: (inst("trouble_ticket_{trouble_ticket_id}", d), EX.alarmMitigatedBy, s)
        ]
    },

    # 16
    "VerifyActionEffects": {
        "subject": lambda d: inst("action_{action_id}", d),
        "triples": [
            lambda s, d: (s, EX.operationPlanPostCondition, lit(d.get("expected_effect")))
        ]
    },

    # 17
    "GetIncidentSummary": {
        "subject": lambda d: inst("trouble_ticket_{trouble_ticket_id}", d),
        "triples": [
            lambda s, d: (s, EX.troubleTicketStatusCurrent, lit(d.get("status"))),
            lambda s, d: (s, EX.troubleTicketCause, lit(d.get("cause_text"))),
            lambda s, d: (s, EX.notes, lit(d.get("notes")))
        ]
    },

    # 18
    "ListInvolvedAgents": {
        "subject": lambda d: inst("agent_{agent_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Agent),
            lambda s, d: (s, EX.label, lit(d.get("agent_label"))),
            lambda s, d: (inst("trouble_ticket_{trouble_ticket_id}", d), EX.troubleTicketRelatedParty, s)
        ]
    },

    # 19
    "GetIncidentBusinessImpact": {
        "subject": lambda d: inst("trouble_ticket_{trouble_ticket_id}", d),
        "triples": [
            lambda s, d: (s, EX.applicationBusinessImportance, lit(d.get("importance_level")))
        ]
    },

    # 20
    "GetResolutionDeadlines": {
        "subject": lambda d: inst("trouble_ticket_{trouble_ticket_id}", d),
        "triples": [
            lambda s, d: (s, EX.troubleTicketTargetRestorationDateTime, lit(d.get("target_time"))),
            lambda s, d: (s, EX.troubleTicketCommittedRestorationDateTime, lit(d.get("committed_time")))
        ]
    },

    # 21
    "AssessInfrastructureRisk": {
        "subject": lambda d: inst("system_{system_id}", d),
        "triples": [
            lambda s, d: (s, EX.applicationBusinessImportance, lit(d.get("risk_level"))),
            lambda s, d: (s, EX.label, lit(d.get("vulnerability_info")))
        ]
    },

    # 22
    "PredictFailureSequence": {
        "subject": lambda d: inst("pattern_{pattern_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.AnomalyPattern),
            lambda s, d: (s, EX.hasPart, lit(d.get("sequence_description")))
        ]
    },

    # 23
    "OpenTroubleTicket": {
        "subject": lambda d: inst("trouble_ticket_{trouble_ticket_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.TroubleTicket),
            lambda s, d: (s, EX.description, lit(d.get("trouble_ticket_description"))),
            lambda s, d: (s, EX.eventRelatedElement, inst("resource_{resource_id}", d))
        ]
    },

    # 24
    "RegisterNewService": {
        "subject": lambda d: inst("service_{service_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Service),
            lambda s, d: (s, EX.label, lit(d.get("service_name"))),
            lambda s, d: (s, EX.serviceType, lit(d.get("service_type"))),
            lambda s, d: (s, EX.elementManagedBy, lit(d.get("managed_by_team")))
        ]
    },

    # 25
    "RegisterNewResource": {
        "subject": lambda d: inst("resource_{resource_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.Resource),
            lambda s, d: (s, EX.resourceHostName, lit(d.get("hostname"))),
            lambda s, d: (s, EX.resourceSerialNumber, lit(d.get("serial_number"))),
            lambda s, d: (s, EX.resourceType, lit(d.get("resource_type"))),
            lambda s, d: (s, EX.resourceUsageState, lit(d.get("usage_state")))
        ]
    },

    # 26
    "InitializeSystemGroup": {
        "subject": lambda d: inst("system_{system_id}", d),
        "triples": [
            lambda s, d: (s, RDF.type, EX.System),
            lambda s, d: (s, EX.label, lit(d.get("system_label"))),
            lambda s, d: (s, EX.applicationBusinessImportance, lit(d.get("importance_level")))
        ]
    }
}


# =========================================================
# PROCESS JSONL
# =========================================================

with open("./output_parsing/input.jsonl") as f:
    for line in f:
        data = json.loads(line)
        intent = data.get("intent")

        config = INTENT_MAP.get(intent)
        if not config:
            continue

        subject = config["subject"](data)
        if subject is None:
            continue

        for fn in config["triples"]:
            triple = fn(subject, data)
            if None in triple:
                continue
            g.add(triple)


# OUTPUT
with open('./resources/output/noria/llama3.3:70b/1to1/5000t/output.ttl', 'w') as f:
    f.write(g.serialize(format="turtle"))