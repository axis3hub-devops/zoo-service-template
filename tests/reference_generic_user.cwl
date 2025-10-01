cwlVersion: v1.2
$namespaces:
  s: https://schema.org/
s:softwareVersion: 0.1.2
schemas:
  - http://schema.org/version/9.0/schemaorg-current-http.rdf
$graph:

      - class: Workflow
        id: test-zoo-service-template
        label: test-zoo-service-template_label
        doc: test-zoo-service-template_doc
        inputs: {}
        outputs:
          execution_results:
            type: Directory
            outputSource: [process/process_results]
        steps:
          process:
            run: "#process"
            in: {}
            out: [process_results]

      - class: CommandLineTool
        id: process
        baseCommand: python
        arguments:
          - /app/run.py
          - --spatial_extent
          - "10"
          - "20"
          - "30"
          - "40"
        requirements:
          ResourceRequirement:
            coresMax: 1
            ramMax: 1024
        hints:
          DockerRequirement:
            dockerPull: brunifrancesco/zoo_reference_implementation:v5
        inputs: {}
        outputs:
          process_results:
            type: Directory
            outputBinding:
              glob: .