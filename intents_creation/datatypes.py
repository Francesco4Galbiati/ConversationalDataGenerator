from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Union

@dataclass
class TriplePattern:
    subject: str
    predicate: str
    obj: str

@dataclass
class ParsedCQ:
    name: str
    select_vars: List[str] = field(default_factory=list)
    triples: List[TriplePattern] = field(default_factory=list)

@dataclass
class OntologySchema:
    classes: Set[str] = field(default_factory=set)
    object_properties: Set[str] = field(default_factory=set)
    datatype_properties: Set[str] = field(default_factory=set)
    property_domains: Dict[str, str] = field(default_factory=dict)
    property_ranges: Dict[str, str] = field(default_factory=dict)
    subclass_of: Dict[str, Set[str]] = field(default_factory=dict)
    subproperty_of: Dict[str, Set[str]] = field(default_factory=dict)
    inverse_of: Dict[str, str] = field(default_factory=dict)

@dataclass
class GraphNode:
    var: str
    class_name: Optional[str] = None
    status: str = "unknown"
    constant: Optional[str] = None

@dataclass
class GraphRelation:
    subject: str
    predicate: str
    obj: str

@dataclass
class GraphAttribute:
    subject: str
    predicate: str
    slot: str
    datatype: str

@dataclass
class GraphPattern:
    name: str
    selected_vars: List[str] = field(default_factory=list)
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    relations: List[GraphRelation] = field(default_factory=list)
    attributes: List[GraphAttribute] = field(default_factory=list)

@dataclass
class IntentSpec:
    name: str
    preconditions: Dict[str, Dict[str, str]]
    postconditions: Dict[str, Union[Dict[str, str], List[List[str]]]]