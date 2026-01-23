# see https://zoo-project.github.io/workshops/2014/first_service.html#f1
import pathlib
import sys
import re
from typing import Dict
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cwl_helper


# Get from vault
THEMATIC_SERVICES_KUBERNETES_MAPPING = {}

THEMATIC_SERVICES_VAULT_MAPPING = {}


try:
    import zoo
except ImportError:

    class ZooStub(object):
        def __init__(self):
            self.SERVICE_SUCCEEDED = 3
            self.SERVICE_FAILED = 4

        def update_status(self, conf, progress):
            print(f"Status {progress}")

        def _(self, message):
            print(f"invoked _ with {message}")

    zoo = ZooStub()

import json
import os

import yaml
from loguru import logger
from zoo_calrissian_runner import ExecutionHandler, ZooCalrissianRunner

# For DEBUG
import traceback

logger.remove()
logger.add(sys.stderr, level="INFO")

class EoepcaCalrissianRunnerExecutionHandler(ExecutionHandler):
    def __init__(self, conf, dedicated_namespace=False, vault_injector=False):
        super().__init__()
        self.conf = conf
        self.thematic_service_name = "internal"

        # Setup vault, service template config, thematic service config
        # and processing
        self._set_service_template_config()
        self._set_thematic_service_config()
        self._set_processing_stageout_config()

        logger.info("Thematic service name: " + self.thematic_service_name)

        self.process_scope = "indexing"
        self.process_version = None
        self.process_frequency = None
        self._set_process_infos_input()
        logger.info(
            f"Process infos: "
            f"version='{self.process_version}, "
            f"frequency='{self.process_frequency}', "
            f"scope='{self.process_scope}'")

        self.http_proxy_env = os.environ.get("HTTP_PROXY", None)

        self.dedicated_namespace = dedicated_namespace
        self.vault_injector = vault_injector
        if self.vault_injector and not self.dedicated_namespace:
            raise Exception("Cannot use vault injector without dedicated namespace and service account")
        self.feature_collection = None

    def _set_service_template_config(self):
        logger.info("Adding Thematic service configuration ")
        try:
            self.vault_user = self.conf['pod_env_vars']["VAULT_USER"]
            self.vault_password = self.conf['pod_env_vars']["VAULT_PASSWORD"]
            self.vault_url = self.conf['pod_env_vars']["VAULT_URL"]
            self.aws_access_key_id  = self.conf['pod_env_vars']["AWS_ACCESS_KEY_ID"]
            self.aws_secret_access_key =  self.conf['pod_env_vars']["AWS_SECRET_ACCESS_KEY"]
        except Exception as e:
            logger.error("Setting  service template issue: " + str(e))
            logger.error(traceback.format_exc())
            raise(e)

    def _set_process_infos_input(self):
        logger.info("Adding Process infos")
        try:
            input_request = self.conf['request']['jrequest']
            json_inputs = json.loads(input_request)['inputs']

            self.process_version = json_inputs['process_version']
            self.process_frequency = json_inputs['process_frequency']

            if "scope" in json_inputs:
                process_scope = json_inputs['scope']
                self.process_scope = process_scope
        except Exception as e:
            logger.error("Setting process version issue: " + str(e))
            logger.error(traceback.format_exc())
            raise (e)

    def _set_thematic_service_config(self):
        logger.info("Adding Thematic service configuration ")
        try:
            input_request = self.conf['request']['jrequest']
            logger.info("Input_request: "+ str(input_request))
            service_name = json.loads(input_request)['inputs']['thematic_service_name']
            self.thematic_service_name = service_name
            self.thematic_service_env_vars = {}
            self.thematic_service_vault_path = self._get_env_var("VAULT_PATH")
            self.thematic_service_env_vars = cwl_helper.get_vault_secret_values(
                self.thematic_service_vault_path,
                self.vault_user,
                self.vault_password,
                self.vault_url
            )
            self.thematic_service_env_vars["VAULT_PATH"] = self.thematic_service_vault_path 
            self.thematic_service_env_vars["VAULT_URL"] = self.vault_url
        except Exception as e:
            logger.error("Setting thematic service config issue: " + str(e))
            logger.error(traceback.format_exc())
            raise(e)

    def _set_processing_stageout_config(self):
        logger.info("Adding processing stageout configuration ")
        try:

            self.processing_stageout_vault_path = self.conf['pod_env_vars']["VAULT_PATH_STAGEOUT"]
            self.processing_stageout_env_vars = {}
            self.processing_stageout_image = self.conf['pod_env_vars']["PROCESSING_STAGEOUT_IMAGE"]
            self.processing_stageout_env_vars = cwl_helper.get_vault_secret_values(
                self.processing_stageout_vault_path,
                self.vault_user,
                self.vault_password,
                self.vault_url
            )
            logger.info("processing_stageout_env_vars: "+ str(self.processing_stageout_env_vars))
            self.s3_bucket_name = self._get_env_var("S3_BUCKET_NAME")
            self.processing_stageout_env_vars["S3_BUCKET_NAME"] = self.s3_bucket_name
            self.processing_stageout_env_vars["S3_ENDPOINT_URL"] = self.conf['pod_env_vars'].get("S3_ENDPOINT_URL")
        except Exception as e:
            logger.error("Setting processing stageout config issue: " + str(e))
            logger.error(traceback.format_exc())
            raise(e)

    def pre_execution_hook(self):
        try:
            logger.info("Pre execution hook")
            self.unset_http_proxy_env()

            lenv = self.conf.get("lenv", {})
            if "additional_parameters" not in self.conf:
                self.conf["additional_parameters"] = {}
            self.conf["additional_parameters"]["collection_id"] = lenv.get("usid", "")
            self.conf["additional_parameters"]["process"] = os.path.join("processing-results", self.conf["additional_parameters"]["collection_id"])
        except Exception as e:
            logger.error("ERROR in pre_execution_hook...")
            logger.error(traceback.format_exc())
            raise(e)
        
        finally:
            self.restore_http_proxy_env()

    def upload_logs_to_s3(self, s3_bucket: str, process_id: str, tool_logs: list = None,
                          aws_access_key_id=None, aws_secret_access_key=None):
        """
        Upload log files to S3:
        - Uploads each file from `tool_logs` (assumed relative to workdir).
        - Skips interceptor logs.
        Files are uploaded to s3://<bucket>/<process_id>/<filename>.
        """
        region_name = self.conf['pod_env_vars'].get("AWS_DEFAULT_REGION")
        endpoint_url = self.conf['pod_env_vars'].get("AWS_ENDPOINT_URL")
        logger.info(f"pod_env_vars {str(self.conf['pod_env_vars'])}")
        try:
            logger.info(
                f"Creating S3 client "
                f"(endpoint={endpoint_url}, region={region_name}, "
                f"access_key={aws_access_key_id})"
                f"secret={aws_secret_access_key})"
            )
            s3 = boto3.client(
                        "s3",
                        aws_access_key_id=str(aws_access_key_id),
                        aws_secret_access_key=str(aws_secret_access_key),
                        region_name=region_name,
                        endpoint_url=endpoint_url,
                    )

        except Exception as e:
            logger.error(
                f"Failed to create S3 client (endpoint={endpoint_url}, region={region_name}): {e}"
            )
            return

        if not tool_logs:
            logger.error("No tool logs were found!")
            return

        # Construct the execution workdir
        workdir_name = f"{(self.conf['lenv']['Identifier']).replace('_', '-')}-{self.conf['lenv']['usid']}"
        # 63 chars is the maximum len of the folder names this is zoo/calrissian
        workdir = os.path.join(self.conf["main"]["tmpPath"], workdir_name[:63])

        # Logs to skip
        skip_logs = {
            "./data_analysis_results_interceptor.log",
            "./process_results_interceptor.log",
            "./node_stage_out.log",
        }

        for tlog in tool_logs:
            if tlog in skip_logs:
                logger.info(f"Skipping tool log {tlog}")
                continue

            # Build absolute path under the workdir
            log_path = os.path.join(workdir, tlog.lstrip("./"))
            logger.debug(f"Resolved tool log '{tlog}' → '{log_path}'")

            if not os.path.isfile(log_path):
                logger.info(f"Tool log not found: {log_path}")
                continue

            fname = os.path.basename(log_path)
            key = f"processing-results/{process_id}/console_{fname}"
            if "report.json" in log_path:
                fname = "report.log"
                key = f"processing-results/{process_id}/{fname}"

            try:
                s3.upload_file(log_path, s3_bucket, key)
                logger.info(f"Uploaded tool log {log_path}  s3://{s3_bucket}/{key}")
            except Exception as e:
                logger.error(f"Failed to upload tool log {log_path}: {e}")

    def _get_env_var(self, prefix):
        identifier = '{}_{}'.format(prefix, self.thematic_service_name.upper())
        value = self.conf['pod_env_vars'].get(identifier)

        if not value:
            raise ValueError("No env var found named {}".format(identifier))
        return value

    def post_execution_hook(self, log, output, usage_report, tool_logs):
        try:
            logger.info("Post execution hook")
            self.unset_http_proxy_env()

            # Resolve S3 bucket
            bucket = self._get_env_var("S3_BUCKET_NAME")
            process_id = self.conf["lenv"]["usid"]


            # Upload only CWL tool logs
            logger.info(f"Uploading tool logs to s3://{bucket}/processing-results/{process_id}/")
            if tool_logs is not None:
                tool_logs.append("./report.json")
                self.upload_logs_to_s3(
                    bucket,
                    process_id,
                    tool_logs,
                self.aws_access_key_id,
                self.aws_secret_access_key
                )

        except Exception as e:
            logger.error("ERROR in post_execution_hook...")
            logger.error(traceback.format_exc())
            raise e
        finally:
            self.restore_http_proxy_env()

    def unset_http_proxy_env(self):
        http_proxy = os.environ.pop("HTTP_PROXY", None)
        logger.info(f"Unsetting env HTTP_PROXY, whose value was {http_proxy}")

    def restore_http_proxy_env(self):
        if self.http_proxy_env:
            os.environ["HTTP_PROXY"] = self.http_proxy_env
            logger.info(f"Restoring env HTTP_PROXY, to value {self.http_proxy_env}")

    @staticmethod
    def get_user_name(decodedJwt):
        for key in ["username", "user_name", "preferred_username"]:
            if key in decodedJwt:
                return decodedJwt[key]
        return None

    @staticmethod
    def local_get_file(fileName):
        """
        Read and load the contents of a yaml file

        :param yaml file to load
        """
        try:
            with open(fileName, "r") as file:
                data = yaml.safe_load(file)
            return data
        # if file does not exist
        except FileNotFoundError:
            return {}
        # if file is empty
        except yaml.YAMLError:
            return {}
        # if file is not yaml
        except yaml.scanner.ScannerError:
            return {}

    def get_namespace(self):
        """Returns the namespace based on the thematic_service_name"""
        # Check if the thematic_service_name is mapped
        if self.thematic_service_name.lower() in THEMATIC_SERVICES_KUBERNETES_MAPPING:
            namespace = THEMATIC_SERVICES_KUBERNETES_MAPPING[self.thematic_service_name.lower()]["namespace"]
        else:
            raise ValueError("No namespace found named {}".format(self.thematic_service_name.lower()))

        logger.info(f"Using namespace: {namespace}")
        return namespace

    def get_service_account(self):
        """Returns the service account based on the thematic_service_name"""

        # Check if the thematic_service_name is mapped
        if self.thematic_service_name.lower() in THEMATIC_SERVICES_KUBERNETES_MAPPING:
            service_account = THEMATIC_SERVICES_KUBERNETES_MAPPING[self.thematic_service_name.lower()]["service-account"]
        else:
            raise ValueError("No k8s service-account found named {}".format(self.thematic_service_name.lower()))

        logger.info(f"Using service account: {service_account}")
        return service_account

    def get_pod_env_vars(self):
        logger.info("get_pod_env_vars")
        env_vars = {
            "THEMATIC_SERVICE_NAME": self.thematic_service_name.upper(),
            "PROCESS_VERSION": self.process_version,
            "PROCESS_FREQUENCY": self.process_frequency,
            "PROCESS_SCOPE": self.process_scope,
            "CATALOG_URL":  self.conf['pod_env_vars']['CATALOG_URL'],
            "REGISTRATION_URL":  self.conf['pod_env_vars']['REGISTRATION_URL'],
            "PROCESS_ID": self.conf["lenv"]["usid"],
            "THRESHOLD_FOR_TASKING": self.conf['pod_env_vars']['THRESHOLD_FOR_TASKING'],
            "THRESHOLD_FOR_UNRECOVERABLE_ERROR": self.conf['pod_env_vars']['THRESHOLD_FOR_UNRECOVERABLE_ERROR'],
            "VAULT_URL": self.conf['pod_env_vars'].get("VAULT_URL"),
            "AWS_DEFAULT_REGION": self.conf['pod_env_vars']['AWS_DEFAULT_REGION'],
            "S3_BASE_URL_TEMPLATE": self.conf['pod_env_vars'].get("S3_BASE_URL_TEMPLATE"),
            "DATA_ACCESS_BASE_URL": self.conf['pod_env_vars'].get("DATA_ACCESS_BASE_URL"),
            "AUTH_CATALOG_URL": self.conf['pod_env_vars'].get("AUTH_CATALOG_URL"),
            "GEOSERVER_URL": self.conf['pod_env_vars'].get("GEOSERVER_URL"),
            "KEYCLOAK_URL": self.conf['pod_env_vars'].get("KEYCLOAK_URL"),
            "S3_ENDPOINT_URL": self.conf['pod_env_vars'].get("S3_ENDPOINT_URL"),
        }
        return env_vars

    def get_pod_node_selector(self):
        logger.info("get_pod_node_selector")
        # Dont use custom node Selector. node selection should happen,
        # automatically from the calrissian pod
        
        return {}


    def get_pod_annotations(self) -> dict:
        """
        Build Vault Agent Injector
        Notes:
        - KV v2 READ path is <KV_MOUNT>/data/<path>
        - Template renders ALL keys as: export KEY="value"
        """
        logger.info("get_pod_annotations")
        if not self.dedicated_namespace and not self.vault_injector:
            return

        svc = self.thematic_service_name.lower()
        if svc not in THEMATIC_SERVICES_VAULT_MAPPING:
            raise ValueError(f"No vault pod annotations found named {svc}")

        cfg = THEMATIC_SERVICES_VAULT_MAPPING[svc]

        # Required fields from mapping
        role = cfg["role"]
        name = cfg["name"]              # file name under /vault/secrets
        rel_path = cfg["path"]          # path relative to KV mount (e.g. "land/secret")

        vault_url = self.conf['pod_env_vars'].get("VAULT_URL")
        if not vault_url:
            raise ValueError("No env var found named VAULT_URL")

        kv_mount = self.conf['pod_env_vars'].get("KV_MOUNT")
        if not kv_mount:
            raise ValueError("No env var found named KV_MOUNT")

        # KV v2 read API path uses /data/
        api_path = f"{kv_mount}/data/{rel_path}"

        ann = {
            "vault.hashicorp.com/agent-inject": "true",
            "vault.hashicorp.com/role": role,
            "vault.hashicorp.com/service": vault_url,
            "vault.hashicorp.com/agent-cpu-request": "50m",
            "vault.hashicorp.com/agent-memory-request": "32Mi",
            # secret mapping
            f"vault.hashicorp.com/agent-inject-secret-{name}": api_path,
        }
        return ann



    def get_secrets(self):
        logger.info("get_secrets")
        secrets={
            "imagePullSecrets": self.local_get_file("/assets/pod_imagePullSecrets.yaml"),
            "additionalImagePullSecrets": self.local_get_file("/assets/pod_additionalImagePullSecrets.yaml")
        }
        return secrets

    def get_additional_parameters(self):
        logger.info("get_additional_parameters")
        # sets the additional parameters for the execution
        # of the wrapped Application Package

        additional_parameters = self.conf.get("additional_parameters", {})
        additional_parameters["sub_path"] = self.conf["lenv"]["usid"]
        return additional_parameters

    def handle_outputs(self, log, output, usage_report, tool_logs):
        """
        Handle the output files of the execution.

        :param log: The application log file of the execution.
        :param output: The output file of the execution.
        :param usage_report: The metrics file.
        :param tool_logs: A list of paths to individual workflow step logs.
        """
        try:
            logger.info("handle_outputs")
            logger.info("Tool Logs: " + str(tool_logs))
            logger.info("Outputs: " + str(output))
            logger.info("Log: " + str(log))
            logger.info("Usage Report: " + str(usage_report))

            # Always ensure the dict exists
            if "service_logs" not in self.conf:
                self.conf["service_logs"] = {}

            # Normalize tmpUrl to user path
            self.conf['main']['tmpUrl'] = self.conf['main']['tmpUrl'].replace(
                "temp/", self.conf["auth_env"]["user"] + "/temp/"
            )

            # Build list of link items from tool_logs (may be empty)
            servicesLogs = [
                {
                    "url": os.path.join(
                        self.conf['main']['tmpUrl'],
                        f"{self.conf['lenv']['Identifier']}-{self.conf['lenv']['usid']}",
                        os.path.basename(tool_log),
                    ),
                    "title": f"Tool log {os.path.basename(tool_log)}",
                    "rel": "related",
                }
                for tool_log in (tool_logs or [])
            ]
            # If no logs, just set length=0 and return
            if not servicesLogs:
                self.conf["service_logs"]["length"] = "0"
                return

            # Append entries using your existing key scheme
            cindex = 0
            if "service_logs" in self.conf and self.conf["service_logs"]:
                cindex = 1

            for item in servicesLogs:
                okeys = ["url", "title", "rel"]
                keys = ["url", "title", "rel"]
                if cindex > 0:
                    for j in range(len(keys)):
                        keys[j] = f"{keys[j]}_{cindex}"
                for j in range(len(keys)):
                    self.conf["service_logs"][keys[j]] = item[okeys[j]]
                cindex += 1

            # Length of *this* batch
            self.conf["service_logs"]["length"] = str(len(servicesLogs))

        except Exception as e:
            logger.error("ERROR in handle_outputs...")
            logger.error(traceback.format_exc())
            raise(e)



def {{cookiecutter.workflow_id |replace("-", "_")  }}(conf, inputs, outputs): # noqa

    try:
        logger.info(inputs)
        with open(
            os.path.join(
                pathlib.Path(os.path.realpath(__file__)).parent.absolute(),
                "app-package.cwl",
            ),
            "r",
        ) as stream:
            cwl = yaml.safe_load(stream)
        use_dedicated_namespace = False
        use_vault_injector = False
        execution_handler = EoepcaCalrissianRunnerExecutionHandler(
            conf=conf,
            dedicated_namespace=use_dedicated_namespace,
            vault_injector=use_vault_injector
        )

        input_request = conf['request']['jrequest']
        json_input_request = json.loads(input_request)
        json_inputs = json.loads(input_request)['inputs']
        process_scope = "indexing"
        if "scope" in json_inputs and json_inputs["scope"] == "generic":
            process_scope = "generic"
        finalized_cwl = cwl_helper.finalize_cwl(cwl, execution_handler, process_scope == "indexing")
        os.environ.set("STORAGE_CLASS", "longhorn-db")
        runner = ZooCalrissianRunner(
            cwl=finalized_cwl,
            conf=conf,
            inputs=inputs,
            outputs=outputs,
            execution_handler=execution_handler,
            dedicated_namespace=use_dedicated_namespace
        )
        # DEBUG
        # runner.monitor_interval = 1

        # we are changing the working directory to store the outputs
        # in a directory dedicated to this execution
        logger.info("cookiecutter: using namespace: "+ runner.get_namespace_name())
        # working_dir = os.path.join(conf["main"]["tmpPath"], runner.get_workdir_name())
        working_dir = os.path.join(conf["main"]["tmpPath"], runner.get_workdir_name())

        os.makedirs(
            working_dir,
            mode=0o777,
            exist_ok=True,
        )
        os.chdir(working_dir)

        exit_status = runner.execute()

        if exit_status == zoo.SERVICE_SUCCEEDED:
            logger.info(f"Setting Collection into output key {list(outputs.keys())[0]}")
            outputs[list(outputs.keys())[0]]["value"] = execution_handler.feature_collection
            conf["lenv"]["message"] = zoo._("Execution success.")
            return zoo.SERVICE_SUCCEEDED
        else:
            msg = runner.get_termination_reason()
            if msg["error_msg"] and "requested access to the resource is denied" in msg["error_msg"]:
                # Extract the image name from the error message
                match = re.search(r"Image pull failed=([^;]+)", msg["error_msg"])
                image_name = match.group(1) if match else "unknown image"

                # Replace the error message with the custom one including the image name
                msg["error_msg"] = f"Docker image '{image_name}' cannot be accessed with axis3hub-devops user, please check the URL and the user permissions."
            elif msg["error_msg"] and "Pod unschedulable" in msg["error_msg"]:
                msg["error_msg"] = f"The requested resources were not available at the moment. Please reschedule your process again."
            conf["lenv"]["message"] = json.dumps(msg)
            logger.error(f"Execution failed: {msg}")
            return zoo.SERVICE_FAILED

    except Exception as e:
        logger.error("ERROR in processing execution template...")
        try:
            with open(os.path.join(conf["main"]["tmpPath"], runner.get_workdir_name(),"job.log"),"w",encoding="utf-8") as file:
                file.write(runner.execution.get_log())
            if "service_logs" not in conf:
                conf["service_logs"] = {}
            keys=["url","title","rel"]
            if "length" in conf["service_logs"]:
                for i in range(len(keys)):
                    keys[i]+="_"+str(int(conf["service_logs"]["length"]))
            conf["service_logs"][keys[0]]=os.path.join(conf['main']['tmpUrl'].replace("temp/",conf["auth_env"]["user"]+"/temp/"),
                    runner.get_workdir_name(),
                    "job.log")
            conf["service_logs"][keys[1]]="Job pod log"
            conf["service_logs"][keys[2]]="related"
            conf["service_logs"]["length"]="1"
            logger.info("Job log saved")
        except Exception as e:
            logger.error(f"{str(e)}")
        try:
            tool_logs = runner.execution.get_tool_logs()
            execution_handler.handle_outputs(None, None, None, tool_logs)
        except Exception as e:
            logger.error("Fethcing logs failed!"+str(e))
        stack = traceback.format_exc()
        logger.error(stack)
        conf["lenv"]["message"] = zoo._(f"Exception during execution...\n{stack}\n")
        return zoo.SERVICE_FAILED