# SMC Custom Resource Definition

This document provides the complete Custom Resource Definition (CRD) for the StatefulMultiCluster (SMC) resource.

### https://github.com/example-org/extension-example-smc/blob/main/docs/configuration.md

```yaml
# Source: config/crd/smc-crd.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: smcs.smc.example-org.com
  annotations:
    controller-gen.kubebuilder.io/version: v0.11.1
spec:
  group: smc.example-org.com
  names:
    kind: SMC
    listKind: SMCList
    plural: smcs
    singular: smc
  scope: Namespaced
  versions:
  - name: v1
    schema:
      openAPIV3Schema:
        description: SMC is the Schema for the smcs API
        properties:
          apiVersion:
            description: 'APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources'
            type: string
          kind:
            description: 'Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds'
            type: string
          metadata:
            type: object
          spec:
            description: SMCSpec defines the desired state of SMC
            properties:
              replicas:
                description: Replicas is the number of desired replicas for the StatefulSet
                format: int32
                minimum: 1
                type: integer
              image:
                description: Image specifies the container image to use
                properties:
                  repository:
                    description: Repository is the image repository
                    type: string
                  tag:
                    description: Tag is the image tag
                    type: string
                  pullPolicy:
                    description: PullPolicy describes a policy for if/when to pull a container image
                    enum:
                    - Always
                    - Never
                    - IfNotPresent
                    type: string
                required:
                - repository
                - tag
                type: object
              config:
                description: Config contains application-specific configuration
                properties:
                  logLevel:
                    description: LogLevel sets the logging verbosity
                    enum:
                    - debug
                    - info
                    - warn
                    - error
                    type: string
                  enableMetrics:
                    description: EnableMetrics enables Prometheus metrics exposition
                    type: boolean
                  metricsPort:
                    description: MetricsPort is the port for metrics server
                    format: int32
                    maximum: 65535
                    minimum: 1024
                    type: integer
                  database:
                    description: Database configuration
                    properties:
                      host:
                        description: Host is the database hostname
                        type: string
                      port:
                        description: Port is the database port
                        format: int32
                        maximum: 65535
                        minimum: 1
                        type: integer
                      name:
                        description: Name is the database name
                        type: string
                      sslMode:
                        description: SSLMode configures SSL connection mode
                        enum:
                        - disable
                        - require
                        - verify-ca
                        - verify-full
                        type: string
                      maxConnections:
                        description: MaxConnections sets the maximum number of connections
                        format: int32
                        minimum: 1
                        type: integer
                      credentials:
                        description: Credentials reference for database authentication
                        properties:
                          secretName:
                            description: SecretName references the Kubernetes secret
                            type: string
                          usernameKey:
                            description: UsernameKey is the key for username in secret
                            type: string
                          passwordKey:
                            description: PasswordKey is the key for password in secret
                            type: string
                        required:
                        - secretName
                        - usernameKey
                        - passwordKey
                        type: object
                    required:
                    - host
                    - port
                    - name
                    - credentials
                    type: object
                  cache:
                    description: Cache configuration for Redis
                    properties:
                      enabled:
                        description: Enabled determines if caching is active
                        type: boolean
                      host:
                        description: Host is the Redis hostname
                        type: string
                      port:
                        description: Port is the Redis port
                        format: int32
                        maximum: 65535
                        minimum: 1
                        type: integer
                      ttl:
                        description: TTL is the default time-to-live in seconds
                        format: int32
                        minimum: 0
                        type: integer
                      maxRetries:
                        description: MaxRetries for connection attempts
                        format: int32
                        minimum: 0
                        type: integer
                    required:
                    - enabled
                    type: object
                  messaging:
                    description: Messaging configuration for message queue
                    properties:
                      provider:
                        description: Provider specifies the messaging system
                        enum:
                        - rabbitmq
                        - kafka
                        - nats
                        type: string
                      brokers:
                        description: Brokers is the list of broker addresses
                        items:
                          type: string
                        minItems: 1
                        type: array
                      topic:
                        description: Topic or queue name for messages
                        type: string
                      consumerGroup:
                        description: ConsumerGroup for message consumption
                        type: string
                      retryPolicy:
                        description: RetryPolicy for failed message processing
                        properties:
                          maxAttempts:
                            description: MaxAttempts before moving to dead letter
                            format: int32
                            minimum: 1
                            type: integer
                          backoffInterval:
                            description: BackoffInterval in seconds between retries
                            format: int32
                            minimum: 1
                            type: integer
                          exponentialBackoff:
                            description: ExponentialBackoff enables exponential retry delays
                            type: boolean
                        required:
                        - maxAttempts
                        type: object
                    required:
                    - provider
                    - brokers
                    - topic
                    type: object
                required:
                - logLevel
                - database
                type: object
              storage:
                description: Storage configuration for persistent volumes
                properties:
                  class:
                    description: Class is the StorageClass name
                    type: string
                  size:
                    description: Size is the requested storage size
                    pattern: ^[0-9]+(Gi|Mi|Ti)$
                    type: string
                  accessModes:
                    description: AccessModes for the volume
                    items:
                      enum:
                      - ReadWriteOnce
                      - ReadOnlyMany
                      - ReadWriteMany
                      type: string
                    minItems: 1
                    type: array
                  volumeMode:
                    description: VolumeMode defines if volume is filesystem or block
                    enum:
                    - Filesystem
                    - Block
                    type: string
                required:
                - size
                - accessModes
                type: object
              networking:
                description: Networking configuration
                properties:
                  serviceName:
                    description: ServiceName for the headless service
                    type: string
                  ports:
                    description: Ports to expose on the service
                    items:
                      properties:
                        name:
                          description: Name of the port
                          type: string
                        port:
                          description: Port number
                          format: int32
                          maximum: 65535
                          minimum: 1
                          type: integer
                        targetPort:
                          description: TargetPort on the pod
                          format: int32
                          maximum: 65535
                          minimum: 1
                          type: integer
                        protocol:
                          description: Protocol for the port
                          enum:
                          - TCP
                          - UDP
                          - SCTP
                          type: string
                      required:
                      - name
                      - port
                      type: object
                    minItems: 1
                    type: array
                  ingress:
                    description: Ingress configuration
                    properties:
                      enabled:
                        description: Enabled determines if ingress is created
                        type: boolean
                      className:
                        description: ClassName specifies the ingress class
                        type: string
                      hosts:
                        description: Hosts for ingress rules
                        items:
                          properties:
                            host:
                              description: Host hostname
                              type: string
                            paths:
                              description: Paths for this host
                              items:
                                properties:
                                  path:
                                    description: Path URL path
                                    type: string
                                  pathType:
                                    description: PathType how path is interpreted
                                    enum:
                                    - Exact
                                    - Prefix
                                    - ImplementationSpecific
                                    type: string
                                required:
                                - path
                                - pathType
                                type: object
                              minItems: 1
                              type: array
                          required:
                          - host
                          - paths
                          type: object
                        minItems: 1
                        type: array
                      tls:
                        description: TLS configuration
                        items:
                          properties:
                            secretName:
                              description: SecretName containing TLS cert and key
                              type: string
                            hosts:
                              description: Hosts covered by this TLS cert
                              items:
                                type: string
                              minItems: 1
                              type: array
                          required:
                          - secretName
                          - hosts
                          type: object
                        type: array
                    required:
                    - enabled
                    type: object
                required:
                - serviceName
                - ports
                type: object
              resources:
                description: Resources defines CPU and memory requirements
                properties:
                  limits:
                    description: Limits describes the maximum resources allowed
                    properties:
                      cpu:
                        description: CPU limit
                        pattern: ^[0-9]+m?$
                        type: string
                      memory:
                        description: Memory limit
                        pattern: ^[0-9]+(Mi|Gi)$
                        type: string
                    type: object
                  requests:
                    description: Requests describes the minimum resources required
                    properties:
                      cpu:
                        description: CPU request
                        pattern: ^[0-9]+m?$
                        type: string
                      memory:
                        description: Memory request
                        pattern: ^[0-9]+(Mi|Gi)$
                        type: string
                    type: object
                type: object
              affinity:
                description: Affinity scheduling rules
                properties:
                  podAntiAffinity:
                    description: PodAntiAffinity rules
                    properties:
                      requiredDuringSchedulingIgnoredDuringExecution:
                        description: Required anti-affinity rules
                        items:
                          properties:
                            topologyKey:
                              description: TopologyKey for the rule
                              type: string
                            labelSelector:
                              description: LabelSelector for matching pods
                              properties:
                                matchLabels:
                                  additionalProperties:
                                    type: string
                                  description: MatchLabels key-value pairs
                                  type: object
                              type: object
                          required:
                          - topologyKey
                          type: object
                        type: array
                    type: object
                type: object
              securityContext:
                description: SecurityContext for pods
                properties:
                  runAsUser:
                    description: RunAsUser UID
                    format: int64
                    minimum: 0
                    type: integer
                  runAsGroup:
                    description: RunAsGroup GID
                    format: int64
                    minimum: 0
                    type: integer
                  fsGroup:
                    description: FSGroup for volume ownership
                    format: int64
                    minimum: 0
                    type: integer
                  runAsNonRoot:
                    description: RunAsNonRoot requires non-root user
                    type: boolean
                  seccompProfile:
                    description: SeccompProfile for the pod
                    properties:
                      type:
                        description: Type of seccomp profile
                        enum:
                        - RuntimeDefault
                        - Unconfined
                        - Localhost
                        type: string
                      localhostProfile:
                        description: LocalhostProfile path (when type is Localhost)
                        type: string
                    required:
                    - type
                    type: object
                type: object
              monitoring:
                description: Monitoring and observability settings
                properties:
                  serviceMonitor:
                    description: ServiceMonitor for Prometheus Operator
                    properties:
                      enabled:
                        description: Enabled creates ServiceMonitor resource
                        type: boolean
                      interval:
                        description: Interval between scrapes
                        pattern: ^[0-9]+[sm]$
                        type: string
                      scrapeTimeout:
                        description: ScrapeTimeout for metrics collection
                        pattern: ^[0-9]+[sm]$
                        type: string
                    required:
                    - enabled
                    type: object
                  alerts:
                    description: Alert configuration
                    properties:
                      enabled:
                        description: Enabled creates PrometheusRule resource
                        type: boolean
                      rules:
                        description: Rules for alerting
                        items:
                          properties:
                            alert:
                              description: Alert name
                              type: string
                            expr:
                              description: Expr PromQL expression
                              type: string
                            for:
                              description: For duration before firing
                              pattern: ^[0-9]+[smh]$
                              type: string
                            severity:
                              description: Severity level
                              enum:
                              - critical
                              - warning
                              - info
                              type: string
                          required:
                          - alert
                          - expr
                          type: object
                        type: array
                    required:
                    - enabled
                    type: object
                type: object
            required:
            - replicas
            - image
            - config
            - storage
            - networking
            type: object
          status:
            description: SMCStatus defines the observed state of SMC
            properties:
              conditions:
                description: Conditions represent the latest available observations
                items:
                  properties:
                    type:
                      description: Type of condition
                      type: string
                    status:
                      description: Status of the condition (True, False, Unknown)
                      enum:
                      - "True"
                      - "False"
                      - Unknown
                      type: string
                    lastTransitionTime:
                      description: LastTransitionTime when condition changed
                      format: date-time
                      type: string
                    reason:
                      description: Reason for the condition's last transition
                      type: string
                    message:
                      description: Message with details about the condition
                      type: string
                  required:
                  - type
                  - status
                  type: object
                type: array
              observedGeneration:
                description: ObservedGeneration reflects the generation observed by controller
                format: int64
                type: integer
              replicas:
                description: Replicas is the current number of replicas
                format: int32
                type: integer
              readyReplicas:
                description: ReadyReplicas is the number of ready replicas
                format: int32
                type: integer
              availableReplicas:
                description: AvailableReplicas is the number of available replicas
                format: int32
                type: integer
              phase:
                description: Phase represents the current phase of the SMC
                enum:
                - Pending
                - Running
                - Scaling
                - Failed
                type: string
            type: object
        type: object
    served: true
    storage: true
    subresources:
      status: {}
```

## Usage Example

To create an SMC resource:

```yaml
apiVersion: smc.example-org.com/v1
kind: SMC
metadata:
  name: my-smc
  namespace: production
spec:
  replicas: 3
  image:
    repository: example-org/smc
    tag: "v1.2.3"
    pullPolicy: IfNotPresent
  config:
    logLevel: info
    enableMetrics: true
    metricsPort: 9090
    database:
      host: postgres.database.svc.cluster.local
      port: 5432
      name: smc_db
      sslMode: require
      maxConnections: 50
      credentials:
        secretName: db-credentials
        usernameKey: username
        passwordKey: password
  storage:
    size: 10Gi
    accessModes:
    - ReadWriteOnce
  networking:
    serviceName: smc-service
    ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
```
