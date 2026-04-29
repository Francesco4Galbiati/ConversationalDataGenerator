from intents_creation.functions import intent_spec_to_yaml, parse_competency_question, parsed_cq_to_graph_pattern, print_graph_pattern, print_parsed_cq, load_ontology_schema, \
    graph_pattern_to_intent_spec

prefixes = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ub: <http://www.lehigh.edu/~zhp2/2004/0401/univ-bench.owl#>
"""
queries = [
    {
        'name': 'EnrollGraduateStudentInCourse',
        'query': f"""
            {prefixes}
            SELECT ?X	
            WHERE
                {{?X rdf:type ub:GraduateStudent .
                ?X ub:takesCourse
                <http://www.Department0.University0.edu/GraduateCourse0>}}
        """
    },
    {
        'name': 'GraduateStudent',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y ?Z
            WHERE
                {{?X rdf:type ub:GraduateStudent .
                ?Y rdf:type ub:University .
                ?Z rdf:type ub:Department .
                ?X ub:memberOf ?Z .
                ?Z ub:subOrganizationOf ?Y .
                ?X ub:undergraduateDegreeFrom ?Y}}
        """
    },
    {
        'name': 'SendPublication',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE
            {{?X rdf:type ub:Publication .
            ?X ub:publicationAuthor 
            <http://www.Department0.University0.edu/AssistantProfessor0>}}
        """
    },
    {
        'name': 'HireProfessor',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y1 ?Y2 ?Y3
            WHERE
                {{?X rdf:type ub:Professor .
                ?X ub:worksFor <http://www.University0.edu/Department0> .
                ?X ub:name ?Y1 .
                ?X ub:emailAddress ?Y2 .
                ?X ub:telephone ?Y3}}
        """
    },
    {
        'name': 'ListMember',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE
            {{?X rdf:type ub:Person .
            ?X ub:memberOf <http://www.University0.edu/Department0>}}
        """,
    },
    {
        'name': 'IntroduceStudent',
        'query': f"""
            {prefixes}
            SELECT ?X 
            WHERE 
                {{?X rdf:type ub:Student}}
        """
    },
    {
        'name': 'TakeCourseOfProfessor',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y
            WHERE 
                {{?X rdf:type ub:Student .
                ?Y rdf:type ub:Course .
                ?X ub:takesCourse ?Y .
                <http://www.Department0.University0.edu/AssociateProfessor0> ub:teacherOf ?Y}}
        """
    },
    {
        'name': 'EnrollStudent',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y ?Z
            WHERE
                {{?X rdf:type ub:Student .
                ?Y rdf:type ub:Department .
                ?X ub:memberOf ?Y .
                ?Y ub:subOrganizationOf <http://www.University0.edu/University0> .
                ?X ub:emailAddress ?Z}}
        """
    },
    {
        'name': 'TakeCourseOfAdvisor',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y ?Z
            WHERE
                {{?X rdf:type ub:Student .
                ?Y rdf:type ub:Faculty .
                ?Z rdf:type ub:Course .
                ?X ub:advisor ?Y .
                ?Y ub:teacherOf ?Z .
                ?X ub:takesCourse ?Z}}
        """
    },
    {
        'name': 'TakeCourse',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE
                {{?X rdf:type ub:Student .
                ?X ub:takesCourse
                <http://www.Department0.University0.edu/GraduateCourse0>}}
        """
    },
    {
        'name': 'CreateResearchGroup',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE
                {{?X rdf:type ub:ResearchGroup .
                ?X ub:subOrganizationOf <http://www.University0.edu/University0>}}
        """
    },
    {
        'name': 'NominateDepartmentChair',
        'query': f"""
            {prefixes}
            SELECT ?X ?Y
            WHERE
                {{?X rdf:type ub:Chair .
                ?Y rdf:type ub:Department .
                ?X ub:worksFor ?Y .
                ?Y ub:subOrganizationOf <http://www.University0.edu/University0>}}
        """
    },
    {
        'name': 'DefineAlumnus',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE
                {{?X rdf:type ub:Person .
                <http://www.University0.edu/University0> ub:hasAlumnus ?X}}
        """
    },
    {
        'name': 'IntroduceUndergraduateStudent',
        'query': f"""
            {prefixes}
            SELECT ?X
            WHERE 
                {{?X rdf:type ub:UndergraduateStudent}}
        """
    }
]

for query in queries:
    schema = load_ontology_schema("./resources/ontologies/lubm_ontology.owl", fmt="xml")
    parsed = parse_competency_question(query['name'], query['query'])
    pattern = parsed_cq_to_graph_pattern(parsed, schema)
    intent = graph_pattern_to_intent_spec(
        pattern,
        description="",
        cardinality=0,
    )
    with open("./resources/contracts/LUBM_test.yaml", "a") as f:
        f.write(intent_spec_to_yaml(intent) + '\n')