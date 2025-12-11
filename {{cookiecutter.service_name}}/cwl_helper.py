"""Helpers for finalizing CWL graphs and injecting environment variables."""

import json
from typing import Any, Dict, List

import requests
from loguru import logger

_SKIP_IDS = {"data_analysis_results_interceptor", "process_results_interceptor", "s3_upload_interceptor"}


def _get_default_processing_image(cwl: Dict[str, Any]) -> str:
    """Return a fallback Docker image from the existing CWL graph."""
    for graph in cwl.get("$graph", []):
        if not isinstance(graph, dict):
            continue
        docker_requirement = graph.get("hints", {}).get("DockerRequirement", {})
        docker_pull = docker_requirement.get("dockerPull")
        if docker_pull:
            return docker_pull
    return ""

def update_workflow_graph(workflow_graph, is_indexing: bool = True):
    """Update the workflow graph with interceptor steps."""
    if is_indexing:
        # Add data analysis interceptor
        workflow_graph["steps"]["data_analysis_results_interceptor"] = {
                "run": "#data_analysis_results_interceptor",
                "in": {"execution_results": "analyse/data_analysis_results"},
                "out": ["data_analysis_results_interceptor_results"],
            }
        workflow_graph["steps"]["process"]["in"]["data_analysis_results_interceptor_results"] = "data_analysis_results_interceptor/data_analysis_results_interceptor_results"
        # Add s3 upload interceptor
        workflow_graph["steps"]["s3_upload_interceptor"] = {
            "run": "#s3_upload_interceptor",
            "in": {"execution_results": "process/process_results",
                    "process_results_interceptor_results_in": "process_results_interceptor/process_results_interceptor_results",
                },
            "out": ["s3_upload_interceptor_results"],
        }
    workflow_graph["steps"]["process_results_interceptor"] = {
            "run": "#process_results_interceptor",
            "in": {"execution_results": "process/process_results"},
            "out": ["process_results_interceptor_results"],
        }
    return workflow_graph

def update_process_graph(process_graph):
    """Add interceptor input wiring to the process graph."""
    process_graph["inputs"]["data_analysis_results_interceptor_results"] = {
            "type": "Directory",
        }
    return process_graph

def add_data_analysis_results_interceptor_graph(processing_stageout_image):
    """Build the data analysis results interceptor tool graph."""
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
                "dockerPull": processing_stageout_image,
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

def add_process_results_interceptor_graph(processing_stageout_image):
    """Build the process results interceptor tool graph."""
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
                "dockerPull": processing_stageout_image,
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

def add_s3_upload_interceptor_graph(processing_stageout_image):
    """Build the S3 upload interceptor tool graph.

    Exposes a 'wf_outputs' Directory input so the workflow can wire
    process_results_interceptor's Directory output into it.
    """
    return {
        "cwlVersion": "v1.0",
        "class": "CommandLineTool",
        "id": "s3_upload_interceptor",
        "inputs": [
            {
                "id": "execution_results",
                "type": "Directory",
            },
            {
                "id": "process_results_interceptor_results_in",
                "type": "Directory",
            }
        ],
        "outputs": {
            "s3_upload_interceptor_results": {
                "outputBinding": {
                    "outputEval": '${  return "Hello from the s3_upload_interceptor"; }'
                },
                "type": "string",
            }
        },
        "baseCommand": ["python"],
        "arguments": [
            "/app/processing/stageout.py",
            "--execution_results",
            "$( inputs.execution_results.path )",
        ],
        "requirements": {
            "DockerRequirement": {
                "dockerPull": processing_stageout_image,
            },
            "ResourceRequirement": {
                "coresMax": 1,
                "ramMax": 10024,
            },
            "InlineJavascriptRequirement": {},
            "InitialWorkDirRequirement": {
                "listing": [
                    {
                        "entry": "$(inputs.execution_results)",
                        "writable": True,
                    }
                ]
            },
        },
    }


def finalize_cwl(cwl, execution_handler=None, is_indexing: bool = True):
    """Finalize the CWL graph for execution."""
    thematic_service_env_vars = {}
    processing_stageout_env_vars = {}
    processing_stageout_image = _get_default_processing_image(cwl)
    if execution_handler is not None:
        thematic_service_env_vars = getattr(
            execution_handler, "thematic_service_env_vars", {}
        )
        processing_stageout_env_vars = getattr(
            execution_handler, "processing_stageout_env_vars", {}
        )
        processing_stageout_image = getattr(
            execution_handler,
            "processing_stageout_image",
            processing_stageout_image,
        )
    logger.info(
        f"Finalizing CWL with \nthematic env vars {thematic_service_env_vars}" \
        f"\nStage out env vars {processing_stageout_env_vars}"
        f"\nProcessing stage out vars {processing_stageout_image}"
    )
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
        graphs.append(add_data_analysis_results_interceptor_graph(processing_stageout_image))
        graphs.append(add_s3_upload_interceptor_graph(processing_stageout_image))

    graphs.append(add_process_results_interceptor_graph(processing_stageout_image))

    # Add Environment variables
    # User CWL steps get updated env vars from their kv secret engine path
    # S3 Upload gets processing stage out
    cwl = add_cwl_env_vars(
            cwl=cwl,
            thematic_service_env_vars=thematic_service_env_vars,
            processing_stageout_env_vars=processing_stageout_env_vars
        )
    pretty = json.dumps(cwl, indent=4)

    logger.info("---Finalized CWL --- Start")

    for line in pretty.splitlines():
        logger.info(line)
    logger.info("---Finalized CWL --- Start")

    return cwl

def get_vault_secret_values(
    thematic_service_vault_path: str,
    user: str,
    password: str,
    vault_url: str,
    *,
    timeout: float = 10.0,
    verify_tls: bool = True,
) -> dict:
    """Authenticate to Vault via userpass and return the secret payload.

    for the secret mapped to `thematic_service`.

    Returns:
        dict: Secret key/value pairs if successful.
    """
    base = vault_url.rstrip("/")
    login_url = f"{base}/v1/auth/userpass/login/{user}"
    secret_url = f"{base}/v1/{thematic_service_vault_path}"

    try:
        with requests.Session() as s:
            # Login
            resp = s.post(login_url, json={"password": password}, timeout=timeout, verify=verify_tls)
            if resp.status_code != 200:
                logger.error(f"Vault login failed ({resp.status_code}): {resp.text}")
                return {}

            token = resp.json().get("auth", {}).get("client_token")
            if not token:
                logger.error("Vault login response missing auth.client_token")
                return {}
            logger.info(f"vault token: {token}")
            # Fetch secret
            headers = {"X-Vault-Token": token}
            resp = s.get(secret_url, headers=headers, timeout=timeout, verify=verify_tls)
            if resp.status_code != 200:
                logger.error(f"Vault secret read failed ({resp.status_code}) at {thematic_service_vault_path}: {resp.text}")
                return {}

            payload = resp.json()
            env_vars = payload.get("data", {}).get("data")
            if env_vars == {}:
                logger.error("Vault secret response missing data.data")
                return {}

            logger.info(f"Successfully retrieved secrets for '{thematic_service_vault_path}'.")
            return env_vars

    except requests.RequestException as e:
        logger.error(f"Request to Vault failed: {e}")
        return {}
    except Exception as e:
        logger.exception(f"Unexpected error retrieving Vault secrets: {e}")
    
    return None

def _ensure_requirements_dict_or_list(node: Dict[str, Any]) -> None:
    """Ensure 'requirements' exists; create an empty dict if missing."""
    if "requirements" not in node or node["requirements"] is None:
        node["requirements"] = {}

def _get_envvar_requirement(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Always normalize to:
    
    requirements:
      EnvVarRequirement:
        envDef: { ... }

    No validation — overwrite anything that is not a dict.
    """
    reqs = node.get("requirements")

    # If requirements is missing or not a dict → replace with empty dict.
    if not isinstance(reqs, dict):
        reqs = {}
        node["requirements"] = reqs

    evr = reqs.get("EnvVarRequirement")

    # If missing or not a dict → replace with {"envDef": {}}
    if not isinstance(evr, dict):
        evr = {"envDef": {}}
        reqs["EnvVarRequirement"] = evr

    env_def = evr.get("envDef")

    # If missing or not a dict → replace with empty dict
    if not isinstance(env_def, dict):
        env_def = {}
        evr["envDef"] = env_def

    return env_def

def _merge_env(env_def: Dict[str, Any],
               new_vars: Dict[str, Any],
               overwrite: bool = False) -> None:
    """Merge dict-style env vars into dict-style env_def."""
    if not new_vars:
        return
    for k, v in new_vars.items():
        if overwrite or k not in env_def:
            env_def[str(k)] = str(v)

def add_cwl_env_vars(cwl: Dict[str, Any],
                     thematic_service_env_vars: Dict[str, Any],
                     processing_stageout_env_vars: Dict[str, Any]) -> Dict[str, Any]:
    """Add env vars to CWL CommandLineTools.

    Behavior:
      - Always add processing_stage_env_vars to ALL CommandLineTools.
      - Add processing_stageout_env_vars ONLY to tools whose id is not in _SKIP_IDS.
    Creates requirements/EnvVarRequirement if missing. Does not overwrite existing envs.
    Returns the modified CWL object.
    """
    graph = cwl.get("$graph", [])
    for node in graph:
        if not isinstance(node, dict):
            continue
        if node.get("class") != "CommandLineTool":
            continue

        tool_id = node.get("id", "")
        _ensure_requirements_dict_or_list(node)
        env_def = _get_envvar_requirement(node)

        # Always add processing-stage env vars
        if tool_id in _SKIP_IDS:
            _merge_env(env_def, processing_stageout_env_vars, overwrite=False)

        # Add thematic-service env vars unless this tool is skipped
        if tool_id not in _SKIP_IDS:
            _merge_env(env_def, thematic_service_env_vars, overwrite=True)

    logger.info(f"finalized cwl {str(cwl)}")

    return cwl
