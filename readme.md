Thi is a python script that walk a directory containing Visual Studio projects and generate a [GraphML](http://graphml.graphdrawing.org/) diagram where nodes are projects and edges are dependencies between projects. The GraphML file can then be visualized, manipulated and exported with a tool like [yEd](http://www.yworks.com/en/products/yfiles/yed/)

### Requisites

This is a Python script, so you need to have Python 3+ installed.

### Usage

Run the script with this command:

```
py -3 dependency_graph.py C:\path\to\codebase
```

When the script terminate execution, you should have the following files in the current directory:

* `out.graphml` This is the generated graph
* `extra_attrs_new.json` This files contain all the found project that are not already mentioned in `extra_attrs.json`. This file is used to add extra metadata in the generated graph, in the form of custom attributes.
* `log.txt` This is the log of the execution, usefult for troubleshooting and development
