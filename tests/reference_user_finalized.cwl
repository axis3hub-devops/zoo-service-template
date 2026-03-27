$graph:
- arguments:
  - /app/data_availability.py
  - --spatial_extent
  - $(inputs.spatial_extent[0])
  - $(inputs.spatial_extent[1])
  - $(inputs.spatial_extent[2])
  - $(inputs.spatial_extent[3])
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
  id: analyse
  inputs:
    spatial_extent:
      type: string[]
  outputs:
    data_analysis_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    EnvVarRequirement:
      envDef: []
    ResourceRequirement:
      coresMax: 1
      ramMax: 512
- class: Workflow
  doc: test-zoo-service-template_doc
  id: test-zoo-service-template
  inputs:
    spatial_extent:
      label: Spatial extent bounding box [minLon, minLat, maxLon, maxLat]
      type: string[]
  label: test-zoo-service-template_label
  outputs:
    execution_results:
      outputSource:
      - process/process_results
      type: Directory
  steps:
    analyse:
      in:
        spatial_extent: spatial_extent
      out:
      - data_analysis_results
      run: '#analyse'
    data_analysis_results_interceptor:
      in:
        execution_results: analyse/data_analysis_results
      out:
      - data_analysis_results_interceptor_results
      run: '#data_analysis_results_interceptor'
    process:
      in:
        data_analysis_results: analyse/data_analysis_results
        data_analysis_results_interceptor_results: data_analysis_results_interceptor/data_analysis_results_interceptor_results
        spatial_extent: spatial_extent
      out:
      - process_results
      run: '#process'
    process_results_interceptor:
      in:
        execution_results: process/process_results
      out:
      - process_results_interceptor_results
      run: '#process_results_interceptor'
    s3_upload_interceptor:
      in:
        execution_results: process/process_results
        process_results_interceptor_results_in: process_results_interceptor/process_results_interceptor_results
      out:
      - s3_upload_interceptor_results
      run: '#s3_upload_interceptor'
- arguments:
  - /app/run.py
  - --spatial_extent
  - $(inputs.spatial_extent[0])
  - $(inputs.spatial_extent[1])
  - $(inputs.spatial_extent[2])
  - $(inputs.spatial_extent[3])
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
  id: process
  inputs:
    data_analysis_results:
      type: Directory
    data_analysis_results_interceptor_results:
      type: Directory
    spatial_extent:
      type: string[]
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
- arguments:
  - /app/processing/results_interceptor.py
  - --execution_results
  - $(inputs.execution_results)
  - --step_name
  - analyse
  baseCommand: python
  class: CommandLineTool
  hints:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
  id: data_analysis_results_interceptor
  inputs:
    execution_results:
      type: Directory
  outputs:
    data_analysis_results_interceptor_results:
      outputBinding:
        glob: .
      type: Directory
  requirements:
    EnvVarRequirement:
      envDef: []
    ResourceRequirement:
      coresMax: 1
      ramMax: 512
- arguments:
  - /app/processing/stageout.py
  - --execution_results
  - $( inputs.execution_results.path )
  baseCommand:
  - python
  class: CommandLineTool
  cwlVersion: v1.0
  id: s3_upload_interceptor
  inputs:
  - id: execution_results
    type: Directory
  - id: process_results_interceptor_results_in
    type: Directory
  outputs:
    s3_upload_interceptor_results:
      outputBinding:
        outputEval: ${  return "Hello from the s3_upload_interceptor"; }
      type: string
  requirements:
    DockerRequirement:
      dockerPull: brunifrancesco/zoo_reference_implementation:v5
    EnvVarRequirement:
      envDef: []
    InitialWorkDirRequirement:
      listing:
      - entry: $(inputs.execution_results)
        writable: true
    InlineJavascriptRequirement: {}
    ResourceRequirement:
      coresMax: 1
      ramMax: 512
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
