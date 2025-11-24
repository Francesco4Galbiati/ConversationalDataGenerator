import os
import pydot

os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"
graph = pydot.Dot("my_graph", graph_type="graph", bgcolor="white")

# Add nodes
my_node = pydot.Node("a", label="Foo")
graph.add_node(my_node)
# Or, without using an intermediate variable:
graph.add_node(pydot.Node("b", shape="circle"))

# Add edges
my_edge = pydot.Edge("a", "b", color="blue")
graph.add_edge(my_edge)
# Or, without using an intermediate variable:
graph.add_edge(pydot.Edge("b", "c", color="blue"))

print(graph.get_node("a"))
print(graph.get_node("e"))

graph.write_png('../resources/graph.png')