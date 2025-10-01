def update_workflow_graph(workflow_graph, is_indexing: bool = True):
    if is_indexing:
        workflow_graph["steps"]["data_analysis_results_interceptor"] = {
                "run": "#data_analysis_results_interceptor",
                "in": {"execution_results": "analyse/data_analysis_results"},
                "out": ["data_analysis_results_interceptor_results"],
            }
        workflow_graph["steps"]["process"]["in"]["data_analysis_results_interceptor_results"] = "data_analysis_results_interceptor/data_analysis_results_interceptor_results"
    workflow_graph["steps"]["process_results_interceptor"] = {
            "run": "#process_results_interceptor",
            "in": {"execution_results": "process/process_results"},
            "out": ["process_results_interceptor_results"],
        }
    return workflow_graph

def update_process_graph(process_graph):
    process_graph["inputs"]["data_analysis_results_interceptor_results"] = {
            "type": "Directory",
        }
    return process_graph

def add_data_analysis_results_interceptor_graph():
    return {
        "class": "CommandLineTool",
        "id": "data_analysis_results_interceptor",
        "baseCommand": "python",
        "arguments": [
            "/app/processing/results_interceptor.py",
            "--execution_results",
            "$(inputs.execution_results)",
            "--step_name",
            "analyse"
        ],
        "requirements": {
            "ResourceRequirement": {
                "coresMax": 1,
                "ramMax": 512,
            }
        },
        "hints": {
            "DockerRequirement": {
                "dockerPull": "ghcr.io/hellenicspacecenter/axis3-hub-processing-stageout:dev-6859",
            }
        },
        "inputs": {
            "execution_results": {
                "type": "Directory"
            }
        },
        "outputs": {
            "data_analysis_results_interceptor_results": {
                "type": "Directory",
                "outputBinding": {
                    "glob": "."
                }
            }
        }
    }

def add_process_results_interceptor_graph():
    return {
        "class": "CommandLineTool",
        "id": "process_results_interceptor",
        "baseCommand": "python",
        "arguments": [
            "/app/processing/results_interceptor.py",
            "--execution_results",
            "$(inputs.execution_results)",
            "--step_name",
            "process"
        ],
        "requirements": {
            "ResourceRequirement": {
                "coresMax": 1,
                "ramMax": 512,
            }
        },
        "hints": {
            "DockerRequirement": {
                "dockerPull": "ghcr.io/hellenicspacecenter/axis3-hub-processing-stageout:dev-6859",
            }
        },
        "inputs": {
            "execution_results": {
                "type": "Directory"
            }
        },
        "outputs": {
            "process_results_interceptor_results": {
                "type": "Directory",
                "outputBinding": {
                    "glob": "."
                }
            }
        }
    }

def finalize_cwl(cwl, is_indexing: bool = True):
    graphs = cwl["$graph"]
    for graph in graphs:
        if graph["class"] == "Workflow":
            updated_workflow_graph = update_workflow_graph(graph, is_indexing)
            graphs.remove(graph)
            graphs.append(updated_workflow_graph)
        if is_indexing and graph["class"] == "CommandLineTool" and graph["id"] == "process":
            updated_process_graph = update_process_graph(graph)
            graphs.remove(graph)
            graphs.append(updated_process_graph)
    if is_indexing:
        graphs.append(add_data_analysis_results_interceptor_graph())
    graphs.append(add_process_results_interceptor_graph())
    return cwl
