$graph:
- arguments:
  - /app/run.py
  - --spatial_extent
  - '10'
  - '20'
  - '30'
  - '40'
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
  id: process
  inputs: {}
  outputs:
    process_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    EnvVarRequirement:
      envDef: []
    ResourceRequirement:
      coresMax: 1
      ramMax: 1024
- class: Workflow
  doc: test-zoo-service-template_doc
  id: test-zoo-service-template
  inputs: {}
  label: test-zoo-service-template_label
  outputs:
    execution_results:
      outputSource:
      - process/process_results
      type: Directory
  steps:
    process:
      in: {}
      out:
      - process_results
      run: '#process'
    process_results_interceptor:
      in:
        execution_results: process/process_results
      out:
      - process_results_interceptor_results
      run: '#process_results_interceptor'
- arguments:
  - /app/processing/results_interceptor.py
  - --execution_results
  - $(inputs.execution_results)
  - --step_name
  - process
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
  id: process_results_interceptor
  inputs:
    execution_results:
      type: Directory
  outputs:
    process_results_interceptor_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    EnvVarRequirement:
      envDef: []
    ResourceRequirement:
      coresMax: 1
      ramMax: 512
$namespaces:
  s: https://schema.org/
cwlVersion: v1.2
s:softwareVersion: 0.1.2
schemas:
- http://schema.org/version/9.0/schemaorg-current-http.rdf
