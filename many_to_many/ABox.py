from rdflib import Graph

num_abox = 3

class ABox:

    def __init__(self, id):
        self.graph = Graph()
        self.id = id
